"""Conservative PDF extraction. No network or generative model dependencies."""
import collections
import hashlib
import json
import re
from pathlib import Path

VERSION = '1.0.0'
NUMBER = re.compile(r'(?m)^\s*(?:Question\s+)?(\d{1,3}(?:\.\d{1,3})?)[.):]\s+', re.I)
OPTION = re.compile(r'(?m)^\s*([A-Ha-h])[.)]\s+')

def flag(category, code, message, location='paper'):
    return dict(id=f'{code}:{location}', category=category, code=code, location=location, message=message)

def points(text):
    marks = re.findall(r'[\[(]\s*(\d+(?:\.\d+)?)\s*(?:points?|pts?)\.?\s*[\])]', text, re.I)
    if not marks:
        return None
    leading = re.match(r'\s*[\[(]\s*(\d+(?:\.\d+)?)\s*(?:points?|pts?)', text, re.I)
    return float(leading[1]) if leading else sum(map(float, marks))

def numbered(pages):
    result, issues, seen = [], [], collections.Counter()
    for p in pages:
        hits = list(NUMBER.finditer(p['text']))
        if not hits and result and p['text'].strip():
            result[-1]['text'] += '\n' + p['text'].strip()
        for i, hit in enumerate(hits):
            n = hit[1]
            seen[n] += 1
            id = n if seen[n] == 1 else f'{n}-repeat-{seen[n]}'
            if seen[n] > 1:
                issues.append(flag('unclear_formatting', 'repeated_number',
                                   f'Question {n} repeats. Review section boundaries or cover instructions.', id))
            result.append(dict(id=id, number=n, page=p['page'], text=p['text'][hit.end():hits[i+1].start() if i+1 < len(hits) else len(p['text'])].strip()))
        # Include a question's continuation before the first number on the next page.
        if hits and hits[0].start() and len(result) > len(hits):
            result[-len(hits)-1]['text'] += '\n' + p['text'][:hits[0].start()].strip()
    return result, issues

def inspect_text(paper_pages, key_pages):
    qs, issues = numbered(paper_pages)
    ks, key_issues = numbered(key_pages)
    issues.extend({**f, 'id': 'key-' + f['id'], 'location': 'key ' + f['location']} for f in key_issues)
    key_by_number = collections.defaultdict(list)
    for k in ks:
        key_by_number[k['number']].append(k)
    full_text = '\n'.join(p['text'] for p in paper_pages)
    default = re.search(r'(?:each question|all questions|every question)\s+(?:is\s+)?(?:worth\s+)?(\d+(?:\.\d+)?)\s*points?', full_text, re.I)
    if default and re.search('unless|except', full_text, re.I):
        default = None  # Exceptions need section-specific review.
    if not qs:
        issues.append(flag('unclear_formatting', 'no_questions', 'No reliable numbered questions found. The complete text and PDFs remain available.'))
    if not key_pages:
        issues.append(flag('missing_answers', 'no_key', 'No usable answer-key PDF. Supply a key or transcribe a reviewed rubric before approval.'))
    if {q['number'] for q in qs} != set(key_by_number):
        issues.append(flag('missing_answers', 'key_numbering', 'Question numbers and answer-key numbers do not match. Review missing and extra items.'))
    if [q['number'] for q in qs if q['number'].isdigit()] != [str(i) for i in range(1, len(qs)+1)]:
        issues.append(flag('unclear_formatting', 'number_sequence', 'Non-continuous numbering or subsections detected. Verify that every item is included.'))
    fields = []
    for q in qs:
        id, text = q['id'], q['text']
        candidates = key_by_number.get(q['number'], [])
        answer = candidates[0]['text'] if len(candidates) == 1 else ''
        if not answer or re.fullmatch(r'[\s_.-]*|(?:answers? (?:may )?var(?:y|ies)|see (?:image|diagram|rubric))\.?', answer, re.I):
            issues.append(flag('missing_answers', 'missing_answer', 'No unique, substantive answer was extracted.', id))
        if text and len(text) > 30 and answer.startswith(text[:min(60, len(text))]):
            issues.append(flag('unclear_formatting', 'repeated_question_in_key', 'The key repeats the question. Correct choices may be bold, colored or handwritten; inspect the original key.', id))
        qp, kp = points(text), points(answer)
        if qp is not None and kp is not None and abs(qp-kp) > 1e-8:
            issues.append(flag('conflicting_scores', 'question_weight_mismatch', f'Test says {qp:g} points; key text suggests {kp:g}. Check totals versus rubric subparts.', id))
        value = qp if qp is not None else kp if kp is not None else float(default[1]) if default else None
        if value is None:
            issues.append(flag('conflicting_scores', 'missing_weight', 'No explicit point value. Do not assume one point without review.', id))
        hits = list(OPTION.finditer(text))
        choices = [dict(id=h[1].upper(), text=text[h.end():hits[i+1].start() if i+1 < len(hits) else len(text)].strip()) for i,h in enumerate(hits)]
        valid_choices = len(choices) >= 2 and [c['id'] for c in choices] == list('ABCDEFGH'[:len(choices)]) and all(c['text'] for c in choices)
        letter = re.fullmatch(r'\s*(?:Answer\s*:\s*)?([A-H])\s*[.)]?\s*(?:\(\s*\d+\s*(?:points?|pts?)\s*\))?\s*', answer, re.I)
        kind = 'mcq' if valid_choices and letter else 'frq'
        if hits and kind != 'mcq':
            issues.append(flag('unclear_formatting', 'choice_or_subpart', 'Could be answer choices or written subparts. Verify question type and all parts.', id))
        if kind == 'mcq' and letter[1].upper() not in [c['id'] for c in choices]:
            issues.append(flag('missing_answers', 'invalid_choice', 'Key letter is absent from the question choices.', id))
        if re.search(r'figure|diagram|pictured|image|graph|draw|table|specimen|sample\s+[A-Z0-9]', text, re.I):
            issues.append(flag('unclear_formatting', 'visual_context', 'Check the original diagram/table/specimen and transcribe enough rubric detail to grade it.', id))
        if re.search(r'(?m)^\s*[a-h][.)]\s+', text) and kind == 'frq':
            issues.append(flag('unclear_formatting', 'multipart_rubric', 'Written subparts detected. Verify that the answer and points cover every part.', id))
        fields.append(dict(id=id, sourceNumber=q['number'], page=q['page'], prompt=text[:hits[0].start()].strip() if kind == 'mcq' else text,
                           type=kind, options=choices if valid_choices else [], answer=letter[1].upper() if kind == 'mcq' else answer,
                           points=value, accepted=[], context='\n'.join(p['text'] for p in paper_pages if abs(p['page']-q['page']) <= 1)[:24000]))
    cover = '\n'.join(p['text'] for p in paper_pages[:2])
    totals = re.findall(r'(?:total\s*(?:points?|score)?\s*[:=]?\s*|(?:score\s*:?\s*[_\s]*)/\s*)(\d+(?:\.\d+)?)', cover, re.I)
    totals += re.findall(r'\b(\d+(?:\.\d+)?)\s*(?:total points|points total)\b', cover, re.I)
    totals = sorted(set(map(float, totals)))
    if len(totals)>1:
        issues.append(flag('conflicting_scores', 'multiple_totals', f'Cover contains different possible totals: {totals}.'))
    if fields and all(f['points'] is not None for f in fields) and totals:
        computed = sum(f['points'] for f in fields)
        if any(abs(t-computed)>1e-8 for t in totals):
            issues.append(flag('conflicting_scores', 'total_mismatch', f'Extracted questions total {computed:g}; cover totals: {totals}.'))
    expected = re.search(r'\b(\d{1,3})\s+(?:numbered\s+)?questions\b', cover, re.I)
    if expected and int(expected[1]) != len(fields):
        issues.append(flag('unclear_formatting', 'question_count', f'Cover mentions {expected[1]} questions; extracted {len(fields)}.'))
    issues.append(flag('review_required', 'source_review', 'Check the complete original test/key, question coverage, diagram context, factual accuracy, dates, topics and scoring before approval.'))
    return fields, issues, totals

def extract_pdf(path, output, role, ocr=True):
    import pymupdf
    if Path(path).read_bytes()[:5] != b'%PDF-':
        raise ValueError('Input is not a PDF (it may be an image, HTML download page or other format).')
    result, issues, engine = [], [], None
    with pymupdf.open(path) as doc:
        if doc.needs_pass:
            raise ValueError('This PDF is password-protected. Supply an unlocked copy.')
        for n, page in enumerate(doc):
            text = page.get_text(sort=True)
            blocks = [b for b in page.get_text('blocks') if b[6] == 0 and len(b[4].strip()) > 20]
            left = any(b[2] < page.rect.width*.58 for b in blocks)
            right = any(b[0] > page.rect.width*.42 for b in blocks)
            if left and right:
                issues.append(flag('unclear_formatting', 'columns', 'Possible multiple columns or tables; verify reading order.', f'{role}-page-{n+1}'))
            method = 'pdf_text'
            if len(re.sub(r'\s', '', text)) < 45 or text.count('\ufffd') > 3:
                method = 'ocr_needed'
                if ocr:
                    try:
                        import numpy as np
                        from rapidocr_onnxruntime import RapidOCR
                        if engine is None:
                            engine = RapidOCR(intra_op_num_threads=1, inter_op_num_threads=1)
                        pix = page.get_pixmap(matrix=pymupdf.Matrix(1.7,1.7), alpha=False)
                        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height,pix.width,pix.n)
                        items, _ = engine(img)
                        text = '\n'.join(item[1] for item in (items or []))
                        method = 'local_ocr'
                        if any(item[2] < .85 for item in (items or [])):
                            issues.append(flag('unclear_formatting','low_ocr_confidence','Some OCR text has low confidence. Check symbols and answers.',f'{role}-page-{n+1}'))
                    except Exception as error:
                        issues.append(flag('unclear_formatting','ocr_failed',str(error)[:300],f'{role}-page-{n+1}'))
                issues.append(flag('unclear_formatting','scanned_page','Scanned or unreadable page. OCR is a draft and can misread handwriting, formulas or diagrams.',f'{role}-page-{n+1}'))
            if not text.strip():
                issues.append(flag('unclear_formatting','empty_page','No readable text on this page. Check whether it contains images or is intentionally blank.',f'{role}-page-{n+1}'))
            result.append(dict(page=n+1, text=text, method=method))
        # A cover thumbnail is useful in the dashboard; source PDFs are never rewritten.
        if len(doc):
            pix = doc[0].get_pixmap(matrix=pymupdf.Matrix(.5,.5), alpha=False)
            pix.save(output / f'{role}-cover.png')
    return result, issues

def convert(source, home, folder, fingerprint, ocr=True):
    folder.mkdir(parents=True, exist_ok=True)
    pages, all_issues = {}, []
    for role in ['test','key','supplement']:
        if sum(a['role']==role for a in source.get('assets',[]))>1:
            all_issues.append(flag('unclear_formatting','multiple_'+role,f'Multiple {role} files: combine and review the packet before export. Only the first test/key is extracted.'))
    for role in ['test','key']:
        asset = next((a for a in source.get('assets',[]) if a['role']==role), None)
        pages[role] = []
        if not asset or not asset.get('path'):
            all_issues.append(flag('missing_answers' if role=='key' else 'missing_files',f'missing_{role}',f'{role.title()} PDF is unavailable. Add the file to this job.'))
            continue
        path = (home / asset['path']).resolve()
        if not path.is_relative_to(home.resolve()):
            raise ValueError('Source file must stay inside the converter folder.')
        try:
            if hashlib.sha256(path.read_bytes()).hexdigest()!=asset['sha256']:
                raise ValueError('The source hash changed. Re-import this file before converting.')
            pages[role], findings = extract_pdf(path,folder,role,ocr)
            all_issues.extend(findings)
        except Exception as error:
            all_issues.append(flag('missing_files',f'unreadable_{role}',str(error)[:400]))
    for asset in source.get('assets',[]):
        if asset['role'] == 'supplement' and not asset.get('path'):
            all_issues.append(flag('missing_files','missing_supplement','A listed image/answer sheet is missing: '+asset['name'],asset['sha256'][:12]))
    fields, findings, totals = inspect_text(pages['test'],pages['key'])
    all_issues.extend(findings)
    metadata = {k:source.get(k) for k in ['id','sourceId','sourceUrl','division','eventId','competition','year','level','levelText']}
    metadata.update(season=2027, difficulty='Hard' if len(fields)>75 else 'Medium' if len(fields)>25 else 'Easy',
                    difficultyReason='Suggested from extracted question count only; review the actual content.',
                    topics=[],topicMatch='unverified',alignment='Topic alignment requires review against the current rules.',
                    scoringBasis='',instructions='Use the complete original paper and any supplements. Answer all labeled parts. Click Auto Grade after submitting to review unresolved written explanations.')
    all_issues.append(flag('metadata_review','metadata','Confirm division, event, competition date, reported level, topics, difficulty and scoring notes.'))
    review = dict(id=source['id'],sourceFingerprint=fingerprint,metadata=metadata,fields=fields,resolutions={},reviewer='',reviewNotes='')
    draft = dict(id=source['id'],engineVersion=VERSION,fingerprint=fingerprint,source=source,metadata=metadata,fields=fields,
                 flags=list({f['id']:f for f in all_issues}.values()),coverTotals=totals,
                 pageCounts={r:len(p) for r,p in pages.items()})
    (folder/'extracted.json').write_text(json.dumps(pages,ensure_ascii=False,indent=2),encoding='utf-8')
    (folder/'draft.json').write_text(json.dumps(draft,ensure_ascii=False,indent=2),encoding='utf-8')
    return draft, review
