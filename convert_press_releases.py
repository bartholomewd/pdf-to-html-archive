#!/usr/bin/env python3
#
# SJPD Press Release PDF Archive Converter
# Converts individual PDF press releases into a single HTML archive page.
# Handles: case-number filenames, BY/DATE footer blocks, body date parsing,
#          two-page PDFs, WHO/WHAT/WHEN/WHERE format, and crime-field format.
# python C:\PressReleasefix\convert_press_releases.py         
# =============================================================================
import os
import re
import sys
import pdfplumber
from pypdf import PdfReader
from datetime import datetime, date
from pathlib import Path

# ── Configuration ──────────────────────────────────────────────────────────────
PDF_DIR      = r"C:\PressReleasefix\pdfs"
OUTPUT_FILE  = r"C:\PressReleasefix\2001-2007\home.html"
PDF_SUBDIR   = "pdfs"   # subfolder name relative to the HTML file
TODAY_STR    = datetime.today().strftime("%Y-%m-%d")
FOOTER_CREDIT = "San Jose Police Department"
VERSION_LINE  = f"ver. {TODAY_STR} -- dtb"
# Base URL of the folder where this page is published (no trailing slash).
# Used for canonical tag and JSON-LD structured data.
BASE_URL     = "https://info.sjpd.org/records/press_release_archive/2004-2007"

# ── Julian day helper ──────────────────────────────────────────────────────────
def julian_to_date(year_2digit, julian_day):
    """Convert 2-digit year + julian day to a date object."""
    year = 2000 + int(year_2digit)
    # Clamp to plausible range -- 94 means 1994 not 2094
    if year > 2010:
        year -= 100
    try:
        return datetime.strptime(f"{year} {int(julian_day)}", "%Y %j").date()
    except ValueError:
        return None

# ── Date from filename ─────────────────────────────────────────────────────────
CASE_RE = re.compile(r'(\d{2})-(\d{3})-(\d{4})')

def date_from_filename(filename):
    """Extract date from case-number pattern YY-JJJ-NNNN."""
    m = CASE_RE.search(filename)
    if m:
        return julian_to_date(m.group(1), m.group(2))
    return None

# ── Date from text ─────────────────────────────────────────────────────────────
# Matches: DATE: 4-9-04 / DATE: 10.28.04 / DATE: 12.07.04 / DATE: 6-5-06
DATE_FIELD_RE = re.compile(
    r'DATE:\s*(\d{1,2})[.\-](\d{1,2})[.\-](\d{2,4})', re.IGNORECASE)

# Matches spelled-out dates: "June 6, 2006" / "October 27, 2004"
SPELLED_DATE_RE = re.compile(
    r'\b(January|February|March|April|May|June|July|August|September|October|November|December)'
    r'\s+(\d{1,2}),?\s+(\d{4})\b', re.IGNORECASE)

MONTH_MAP = {m: i for i, m in enumerate(
    ['january','february','march','april','may','june',
     'july','august','september','october','november','december'], 1)}

def date_from_text(text):
    """Try multiple patterns to extract a date from text."""
    # BY/AUTHORIZED footer DATE: field
    for m in DATE_FIELD_RE.finditer(text):
        month, day, year = int(m.group(1)), int(m.group(2)), m.group(3)
        if len(year) == 2:
            year = 2000 + int(year)
        else:
            year = int(year)
        try:
            return date(year, month, day)
        except ValueError:
            continue

    # Spelled-out date in body
    m = SPELLED_DATE_RE.search(text)
    if m:
        month = MONTH_MAP[m.group(1).lower()]
        day   = int(m.group(2))
        year  = int(m.group(3))
        try:
            return date(year, month, day)
        except ValueError:
            pass

    return None

# ── Title extraction ───────────────────────────────────────────────────────────
# Lines to strip as boilerplate
BOILERPLATE = re.compile(
    r'(PRESS\s+RELEASE|PRESS\s+OFFICER\s+BRIEFED|Pursuant\s+to\s+Cal|'
    r'San\s+Jose\s+Police\s+Department|Press\s+Information\s+Office|'
    r'201\s+W\.\s+Mission|Ph\s+\(408\)|Fax\s+\(408\)|BY:\s|AUTHORIZED\s+BY:|'
    r'DATE:\s*\d|TIME:\s*\d|UPDATE~+|MEDIA\s+ADVISORY)',
    re.IGNORECASE)

CRIME_FIELDS = re.compile(
    r'^(TYPE OF CRIME|CASE NUMBER|LOCATION|DATE|TIME|VICTIM|ADDRESS|'
    r'SUSPECT|DRIVER|AGE|WHO|WHAT|WHEN|WHERE)\b',
    re.IGNORECASE)

def extract_title(lines):
    """
    Find the press release headline.
    Some PDFs have the PRESS RELEASE header at top, title below.
    Some have it inverted (header at bottom), title near top.
    """
    crime_type   = None
    media_label  = None
    has_bottom_header = False
    candidates   = []

    # First pass: check if PRESS RELEASE appears near the bottom (inverted layout)
    text_joined = '\n'.join(lines)
    header_positions = [m.start() for m in re.finditer(r'PRESS\s+RELEASE', text_joined, re.IGNORECASE)]
    total_len = len(text_joined)
    if header_positions and all(pos > total_len * 0.5 for pos in header_positions):
        has_bottom_header = True

    # Collect TYPE OF CRIME / MEDIA ADVISORY from entire text regardless of layout
    for line in lines:
        stripped = line.strip()
        m = re.match(r'TYPE\s+OF\s+CRIME[:\s]+(.+)', stripped, re.IGNORECASE)
        if m:
            val = m.group(1).strip().rstrip(',')
            # May have CASE NUMBER appended on same line -- strip it
            val = re.split(r'\s{2,}|CASE\s+NUMBER', val, flags=re.IGNORECASE)[0].strip()
            crime_type = val
        if re.match(r'MEDIA\s+ADVISORY', stripped, re.IGNORECASE):
            media_label = 'Media Advisory'

    if has_bottom_header:
        # Title is typically in the top half, before the body fields
        for line in lines:
            line = line.strip()
            if not line:
                continue
            if BOILERPLATE.search(line):
                continue
            if re.match(r'(BY:|AUTHORIZED|DATE:|TIME:|PRESS OFFICER)', line, re.IGNORECASE):
                continue
            if CRIME_FIELDS.match(line):
                break  # stop at first field label -- title must be above this
            if 4 < len(line) < 120:
                first_word = line.split()[0].lower()
                if first_word not in ('on','at','the','and','of','in','a','is','was','to','anyone','update','detective','pursuant'):
                    candidates.append(line)
    else:
        # Normal layout: PRESS RELEASE header at top, title follows
        past_header = False
        for line in lines:
            line = line.strip()
            if not line:
                continue
            if re.search(r'PRESS\s+RELEASE', line, re.IGNORECASE):
                past_header = True
                continue
            if not past_header:
                continue
            if BOILERPLATE.search(line):
                continue
            if re.match(r'(BY:|AUTHORIZED|DATE:|TIME:|PRESS OFFICER)', line, re.IGNORECASE):
                continue
            if re.match(r'Press\s+Release\s+Case|Page\s+\d', line, re.IGNORECASE):
                continue
            # Stop collecting title candidates once we hit structured fields
            if CRIME_FIELDS.match(line):
                break
            if 4 < len(line) < 120:
                first_word = line.split()[0].lower()
                if first_word not in ('on','at','the','and','of','in','a','is','was','to','anyone','update','detective','pursuant'):
                    candidates.append(line)

    if candidates:
        # Filter out obvious non-titles
        good = [c for c in candidates if not re.match(
            r'^(DETAILS|UPDATE|ADDRESS|ADRESS|WHO|WHAT|WHEN|WHERE|CASE\s*\d)',
            c, re.IGNORECASE) and len(c.split()) > 1]
        if good:
            return good[0]
    if crime_type:
        return crime_type
    if media_label:
        return media_label
    return "Press Release"

# ── Body text cleanup ──────────────────────────────────────────────────────────
SKIP_LINE_RE = re.compile(
    r'(PRESS\s+RELEASE|Pursuant\s+to\s+Cal|San\s+Jose\s+Police\s+Dept.*Press\s+Info|'
    r'201\s+W\.\s+Mission|Ph\s+\(408\)|Fax\s+\(408\)|'
    r'BY:\s|AUTHORIZED\s+BY:|PRESS\s+OFFICER\s+BRIEFED|'
    r'Press\s+Release\s+Case\s+\d|Page\s+\d)',
    re.IGNORECASE)

def clean_body(text, title):
    """Return cleaned body text with boilerplate stripped and paragraphs separated."""
    lines = text.splitlines()
    body_lines = []
    skip_header = True  # skip the top header block
    in_footer_block = False  # track when we're inside a BY/DATE footer block

    for line in lines:
        stripped = line.strip()

        if not stripped:
            # A blank line ends a footer block (next page content may follow)
            if in_footer_block:
                in_footer_block = False
            body_lines.append('')
            continue

        # Once we see the title, stop skipping the initial header
        if skip_header and title.lower() in stripped.lower():
            skip_header = False
            continue

        if skip_header:
            continue

        # Skip repeated page headers on subsequent pages
        if SKIP_LINE_RE.search(stripped):
            continue

        # Skip BY/AUTHORIZED footer lines but do NOT break -- more pages may follow
        if re.match(r'BY:\s+\w', stripped) and 'AUTHORIZED BY' in stripped:
            in_footer_block = True
            continue
        if re.match(r'DATE:\s+\d', stripped) and 'TIME' in stripped:
            in_footer_block = True
            continue

        # If we're in a footer block, skip remaining footer fields until blank line
        if in_footer_block:
            # Footer fields like PRESS OFFICER BRIEFED, DATE:, TIME: on their own lines
            if re.match(r'(PRESS\s+OFFICER|DATE:|TIME:|AUTHORIZED)', stripped, re.IGNORECASE):
                continue
            # If we hit something that doesn't look like a footer field,
            # we've moved past it into next-page content
            in_footer_block = False

        # Skip repeated title on subsequent pages
        if title.lower() in stripped.lower():
            continue

        # Skip page number lines like "Page 2" or "Page 2 of 3"
        if re.match(r'Page\s+\d', stripped, re.IGNORECASE):
            continue

        body_lines.append(stripped)

    # ── Paragraph break injection ──────────────────────────────────────────
    # PDFs often extract as wrapped lines with no blank lines between paragraphs.
    # Insert a blank line when we detect a paragraph boundary:
    #   - Current line ends a sentence (.!?) AND next line starts with a capital
    #   - Next line starts a known section label (DETAILS, UPDATE, SUSPECT, etc.)
    #   - Next line starts with a suspect/victim label pattern (SUSPECT #1:, etc.)

    SECTION_LABEL_RE = re.compile(
        r'^(DETAILS|UPDATE|SUSPECT\s*#?\d*|VICTIM\s*#?\d*|DRIVER\s*#?\d*|'
        r'WHO|WHAT|WHEN|WHERE|ANYONE|NOTE)\b',
        re.IGNORECASE)

    result_lines = []
    for i, line in enumerate(body_lines):
        result_lines.append(line)

        if not line:
            continue

        # Look ahead to next non-empty line
        next_line = None
        for j in range(i + 1, len(body_lines)):
            if body_lines[j].strip():
                next_line = body_lines[j].strip()
                break

        if next_line is None:
            continue

        # Always insert break before a section label
        if SECTION_LABEL_RE.match(next_line):
            result_lines.append('')
            continue

        # Insert break if current line ends a sentence and next starts a new one
        sentence_end = bool(re.search(r'[.!?]["\']?\s*$', line))
        next_starts_capital = bool(re.match(r'[A-Z]', next_line))
        next_starts_connector = bool(re.match(
            r'^(and|or|but|however|the|a|an|in|of|at|on|to|with|while|as|'
            r'although|because|since|when|where|who|which|that)\b',
            next_line, re.IGNORECASE))

        if sentence_end and next_starts_capital and not next_starts_connector:
            result_lines.append('')

    # Collapse 3+ blank lines to 2, strip leading/trailing whitespace
    text_out = '\n'.join(result_lines).strip()
    text_out = re.sub(r'\n{3,}', '\n\n', text_out)
    return text_out



# ── Footer (BY/AUTHORIZED BY) extraction ──────────────────────────────────────
# Matches the combined single-line footer:
#   BY: Sgt. S. Dixon #2650 AUTHORIZED BY: Det. Fred Mills DATE: 4-1-04 TIME: 9:30AM ...
FOOTER_RE = re.compile(
    r'BY:\s*(.+?)\s+AUTHORIZED\s+BY:\s*(.+?)\s+'
    r'DATE:\s*(\d{1,2}[.\-]\d{1,2}[.\-]\d{2,4})\s+'
    r'TIME:\s*(\S+)',
    re.IGNORECASE)

# Also matches two-line footer variant where BY/DATE are on separate lines
BY_RE      = re.compile(r'^BY:\s*(.+?)(?:\s{2,}AUTHORIZED\s+BY:\s*(.+))?$', re.IGNORECASE)
AUTH_RE    = re.compile(r'AUTHORIZED\s+BY:\s*(.+)', re.IGNORECASE)
FOOT_DATE_RE = re.compile(r'DATE:\s*(\d{1,2}[.\-]\d{1,2}[.\-]\d{2,4})', re.IGNORECASE)
FOOT_TIME_RE = re.compile(r'TIME:\s*(\S+)', re.IGNORECASE)

def extract_footer(text):
    """
    Extract BY, AUTHORIZED BY, DATE, TIME from the press release footer block.
    Returns a dict with keys: by, authorized_by, date_str, time_str.
    All values may be None if not found.
    """
    result = {'by': None, 'authorized_by': None, 'date_str': None, 'time_str': None}

    # Try single-line combined pattern first
    m = FOOTER_RE.search(text)
    if m:
        result['by']            = m.group(1).strip()
        result['authorized_by'] = m.group(2).strip()
        result['date_str']      = m.group(3).strip()
        result['time_str']      = m.group(4).strip()
        return result

    # Fall back: scan lines near the bottom for BY:/AUTHORIZED BY: fields
    lines = text.splitlines()
    # Search last 15 lines where footer typically lives
    for line in lines[-15:]:
        stripped = line.strip()

        if not result['by']:
            m = re.match(r'BY:\s*(.+)', stripped, re.IGNORECASE)
            if m:
                by_raw = m.group(1)
                # Split off AUTHORIZED BY if on same line
                auth_split = re.split(r'\s+AUTHORIZED\s+BY:', by_raw, flags=re.IGNORECASE)
                result['by'] = auth_split[0].strip()
                if len(auth_split) > 1:
                    result['authorized_by'] = auth_split[1].strip()

        if not result['authorized_by']:
            m = AUTH_RE.search(stripped)
            if m:
                result['authorized_by'] = m.group(1).strip()

        if not result['date_str']:
            m = FOOT_DATE_RE.search(stripped)
            if m:
                result['date_str'] = m.group(1).strip()

        if not result['time_str']:
            m = FOOT_TIME_RE.search(stripped)
            if m:
                result['time_str'] = m.group(1).strip()

    return result

def format_footer_html(footer):
    """Render the footer dict as an HTML string for the metadata bar."""
    parts = []
    if footer['by']:
        parts.append(f'<span><strong>By:</strong> {html_escape(footer["by"])}</span>')
    if footer['authorized_by']:
        parts.append(f'<span><strong>Authorized by:</strong> {html_escape(footer["authorized_by"])}</span>')
    if footer['date_str'] and footer['time_str']:
        parts.append(f'<span><strong>Date/Time:</strong> {html_escape(footer["date_str"])} &nbsp;{html_escape(footer["time_str"])}</span>')
    elif footer['date_str']:
        parts.append(f'<span><strong>Date:</strong> {html_escape(footer["date_str"])}</span>')
    if not parts:
        return ''
    return ' <span class="meta-sep" aria-hidden="true">|</span> '.join(parts)

# ── PDF extraction ─────────────────────────────────────────────────────────────
def extract_pdf(pdf_path):
    """Extract all text from a PDF (all pages concatenated)."""
    full_text = ""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    full_text += t + "\n"
    except Exception as e:
        print(f"  WARNING pdfplumber failed on {pdf_path.name}: {e}")

    if not full_text.strip():
        try:
            reader = PdfReader(str(pdf_path))
            for page in reader.pages:
                t = page.extract_text()
                if t:
                    full_text += t + "\n"
        except Exception as e:
            print(f"  WARNING pypdf also failed on {pdf_path.name}: {e}")

    return full_text

# ── PDF metadata date ──────────────────────────────────────────────────────────
def date_from_metadata(pdf_path):
    """Try to get a date from PDF metadata."""
    try:
        reader = PdfReader(str(pdf_path))
        meta = reader.metadata
        for field in ['/CreationDate', '/ModDate']:
            raw = meta.get(field, '')
            if raw:
                # Format: D:20040409140000 or D:20040409
                m = re.search(r'D:(\d{4})(\d{2})(\d{2})', str(raw))
                if m:
                    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
                    if 1994 <= y <= 2010:
                        try:
                            return date(y, mo, d)
                        except ValueError:
                            pass
    except Exception:
        pass
    return None

# ── Process one PDF ────────────────────────────────────────────────────────────
def process_pdf(pdf_path):
    """Return dict with title, date, body, filename, warnings."""
    result = {
        'filename': pdf_path.name,
        'pdf_link': f"{PDF_SUBDIR}/{pdf_path.name}",
        'title': 'Press Release',
        'date': None,
        'date_source': 'unknown',
        'body': '',
        'footer': {'by': None, 'authorized_by': None, 'date_str': None, 'time_str': None},
        'warnings': []
    }

    # 1. Extract text first (needed for title + text-based date)
    text = extract_pdf(pdf_path)
    if not text.strip():
        result['warnings'].append('NO TEXT EXTRACTED - may be scanned image')
        # Still try filename date as best guess
        d = date_from_filename(pdf_path.name)
        if d:
            result['date'] = d
            result['date_source'] = 'filename (no text)'
        return result

    lines = text.splitlines()

    # 2. Title
    result['title'] = extract_title(lines)

    # 3. Extract footer early so its date can be used as top priority
    result['footer'] = extract_footer(text)

    # 4. Date priority:
    #      a) Footer BY/DATE field  -- most authoritative, is the release issue date
    #      b) Spelled-out date in body text
    #      c) Filename case number  -- encodes incident date, may differ by months,
    #                                  and pre-2000 files would compute wrong century
    #      d) PDF metadata          -- last resort

    # a) Footer date
    footer_date_str = result['footer'].get('date_str')
    if footer_date_str:
        d = date_from_text(f"DATE: {footer_date_str}")
        if d:
            result['date'] = d
            result['date_source'] = 'footer'

    # b) Spelled-out date in body (skips DATE: field matches to avoid re-using footer)
    if not result['date']:
        m = SPELLED_DATE_RE.search(text)
        if m:
            month = MONTH_MAP[m.group(1).lower()]
            day   = int(m.group(2))
            year  = int(m.group(3))
            try:
                result['date'] = date(year, month, day)
                result['date_source'] = 'body text'
            except ValueError:
                pass

    # c) Filename case number
    if not result['date']:
        d = date_from_filename(pdf_path.name)
        if d:
            result['date'] = d
            result['date_source'] = 'filename'

    # d) PDF metadata
    if not result['date']:
        d = date_from_metadata(pdf_path)
        if d:
            result['date'] = d
            result['date_source'] = 'metadata'

    if not result['date']:
        result['warnings'].append('DATE NOT FOUND')

    # 6. Body
    result['body'] = clean_body(text, result['title'])

    return result

# ── HTML helpers ───────────────────────────────────────────────────────────────
def html_escape(s):
    return (s.replace('&', '&amp;')
             .replace('<', '&lt;')
             .replace('>', '&gt;')
             .replace('"', '&quot;'))

def body_to_html(body):
    """Convert plain text body to HTML paragraphs."""
    paragraphs = re.split(r'\n{2,}', body.strip())
    html = ''
    for p in paragraphs:
        p = p.strip()
        if not p:
            continue
        # Check if paragraph starts with a section label like DETAILS: followed by body text
        label_match = re.match(
            r'^(DETAILS|UPDATE|WHO|WHAT|WHEN|WHERE|SUSPECT|VICTIM)\s*:\s*(.+)',
            p, re.IGNORECASE | re.DOTALL)
        if label_match and label_match.group(2).strip():
            # Split: render label as its own element, rest as normal paragraph
            label = label_match.group(1).upper() + ':'
            rest  = label_match.group(2).strip()
            html += f'<p class="section-label">{html_escape(label)}</p>\n'
            lines = rest.splitlines()
            html += '<p>' + '<br>'.join(html_escape(l) for l in lines if l.strip()) + '</p>\n'
        elif re.match(r'^[A-Z][A-Z\s#]+:?\s*$', p):
            html += f'<p class="section-label">{html_escape(p)}</p>\n'
        else:
            lines = p.splitlines()
            html += '<p>' + '<br>'.join(html_escape(l) for l in lines if l.strip()) + '</p>\n'
    return html

# ── HTML template ──────────────────────────────────────────────────────────────
CSS = """
*, *::before, *::after { box-sizing: border-box; }
body {
  font-family: Arial, Helvetica, sans-serif;
  font-size: 14px;
  color: #222;
  background: #f5f5f5;
  margin: 0;
  padding: 0;
}

/* WCAG 2.4.1 - Skip navigation link, visible on focus only */
.skip-link {
  position: absolute;
  top: -100px;
  left: 0;
  background: #003366;
  color: #ffffff;
  padding: 8px 16px;
  font-size: 1em;
  text-decoration: none;
  z-index: 9999;
  border-radius: 0 0 4px 0;
}
.skip-link:focus {
  top: 0;
}

/* WCAG 2.4.7 - visible focus indicator for all interactive elements */
a:focus,
a:focus-visible {
  outline: 3px solid #c8a800;
  outline-offset: 2px;
  border-radius: 2px;
}

/* ── Page header with search box ────────────────────────────────────────── */
.page-header {
  background: #003366;
  color: #fff;
  padding: 18px 32px 14px;
  border-bottom: 4px solid #c8a800;
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
}
.page-header-text {
  flex: 1;
  min-width: 300px;
}
.page-header h1 {
  margin: 0 0 4px;
  font-size: 22px;
  letter-spacing: 0.5px;
}
.page-header p {
  margin: 0;
  font-size: 13px;
  color: #b0b0b0;
}
.page-header-text h1 a {
    color: inherit;
    text-decoration: none;
}

.page-header-text h1 a:hover {
    color: inherit;
}

.header-subtitle {
    font-size: 13px;
    color: #b0b0b0;
    margin: 0;
    padding-right: 20px;
    align-self: flex-end;
}

.header-subtitle a {
    color: inherit;
    text-decoration: none;
}

.header-subtitle a:hover {
    color: inherit;
}

/* ── Flex wrapper for sidebar + main ────────────────────────────────────── */
.wrapper {
  display: flex;
  align-items: flex-start;
}

/* ── Left sidebar navigation ────────────────────────────────────────────── */
nav.sidebar {
  width: 280px;
  min-width: 280px;
  position: sticky;
  top: 0;
  height: 100vh;
  overflow-y: auto;
  border-right: 2px solid #1a3a6b;
  padding: 16px;
  background: #eef2f9;
}
nav.sidebar h2 {
  font-size: 13px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin: 0 0 12px;
  color: #1a3a6b;
  padding-bottom: 8px;
  border-bottom: 2px solid #1a3a6b;
}
nav.sidebar .back-link {
  display: block;
  font-size: 0.95em;
  color: #1a3a6b;
  text-decoration: underline;
  margin-bottom: 12px;
  padding-bottom: 10px;
  border-bottom: 2px solid #1a3a6b;
}
nav.sidebar .back-link:hover {
  color: #000;
}
nav.sidebar .toc-years {
  margin-bottom: 14px;
  padding-bottom: 10px;
  border-bottom: 1px solid #b0b0b0;
  font-size: 12px;
  line-height: 1.8;
}
nav.sidebar .toc-years a {
  color: #1a3a6b;
  text-decoration: underline;
  margin-right: 6px;
  font-weight: bold;
}
nav.sidebar .toc-years a:hover {
  color: #000;
}
nav.sidebar .year-label {
  font-size: 12px;
  font-weight: bold;
  color: #1a3a6b;
  margin: 14px 0 6px;
  padding-bottom: 4px;
  border-bottom: 1px solid #c8a800;
}
nav.sidebar .year-label:first-of-type {
  margin-top: 0;
}
nav.sidebar ul {
  list-style: none;
  padding: 0;
  margin: 0 0 4px;
}
nav.sidebar ul li {
  margin-bottom: 8px;
  padding-bottom: 8px;
  border-bottom: 1px solid #d0d0d0;
}
nav.sidebar ul li:last-child {
  border-bottom: none;
}
nav.sidebar ul li a {
  display: block;
  font-size: 0.85em;
  color: #1a3a6b;
  text-decoration: underline;
  line-height: 1.4;
}
nav.sidebar ul li a:hover {
  color: #000;
}
nav.sidebar .index-date {
  display: block;
  font-size: 0.8em;
  color: #555;
  margin-top: 2px;
}

/* ── Main content area ──────────────────────────────────────────────────── */
main.content {
  flex: 1;
  max-width: 960px;
  margin: 0;
  padding: 24px 32px;
}
.year-group {
  margin-bottom: 32px;
}
.year-heading {
  font-size: 18px;
  font-weight: bold;
  color: #1a3a6b;
  border-bottom: 2px solid #1a3a6b;
  padding-bottom: 4px;
  margin-bottom: 16px;
}
.release-card {
  background: #fff;
  border: 1px solid #d0d0d0;
  border-left: 4px solid #1a3a6b;
  margin-bottom: 20px;
  padding: 0;
  border-radius: 2px;
}
.release-header {
  background: #eef2f9;
  padding: 10px 16px;
  border-bottom: 1px solid #d0d0d0;
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 12px;
}
.release-title {
  font-size: 15px;
  font-weight: bold;
  color: #1a3a6b;
  flex: 1;
}
.release-date {
  font-size: 12px;
  color: #4a4a4a;
  white-space: nowrap;
}
.release-case {
  font-size: 12px;
  color: #595959;
  white-space: nowrap;
}
.release-body {
  padding: 12px 16px 14px;
  line-height: 1.6;
  font-size: 13px;
}
.release-body p { margin: 0 0 10px; }
.release-body p:last-child { margin-bottom: 0; }
.release-body .section-label {
  font-weight: bold;
  margin-top: 12px;
  margin-bottom: 4px;
  text-transform: uppercase;
  font-size: 13px;
  color: #333;
  letter-spacing: 0.3px;
}
.warning-card {
  border-left-color: #c00;
  background: #fff8f8;
}
.warning-tag {
  font-size: 12px;
  color: #c00;
  background: #ffe0e0;
  padding: 2px 6px;
  border-radius: 2px;
  margin-left: 8px;
}
.pdf-link-bar {
  padding: 8px 16px;
  border-top: 1px solid #dde3f0;
  background: #f5f7fc;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.pdf-link-bar a {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  color: #1a3a6b;
  text-decoration: none;
  font-weight: 600;
  padding: 4px 10px;
  border: 1px solid #1a3a6b;
  border-radius: 3px;
  background: #fff;
  transition: background 0.15s, color 0.15s;
}
.pdf-link-bar a:hover,
.pdf-link-bar a:focus {
  background: #1a3a6b;
  color: #fff;
  outline: 2px solid #c8a800;
  outline-offset: 2px;
}
.pdf-link-bar a svg {
  flex-shrink: 0;
}
.back-to-top {
  font-size: 12px;
  color: #1a3a6b;
  text-decoration: underline;
}
.back-to-top:hover {
  color: #000;
}
.count-badge {
  font-size: 12px;
  color: #555;
  font-weight: normal;
  margin-left: 8px;
}
.release-footer {
  padding: 7px 16px;
  border-top: 1px solid #e8e8e8;
  background: #fafafa;
  font-size: 13px;
  color: #4a4a4a;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}
.release-footer strong {
  color: #2a2a2a;
}
.meta-sep {
  color: #595959;
  padding: 0 2px;
}
.page-footer {
  background: #1a3a6b;
  color: #b0b0b0;
  font-size: 12px;
  padding: 10px 32px;
  display: flex;
  justify-content: space-between;
  margin-top: 32px;
}

@media print {
  .skip-link  { display: none; }
  nav.sidebar { display: none; }
  main.content { max-width: 100%; padding: 10px; }
}
"""

def build_html(records):
    """Build the complete HTML archive page from a list of record dicts."""
    # Sort by date (None dates go to end)
    records.sort(key=lambda r: (r['date'] is None, r['date'] or date(9999,1,1)))

    # Group by year
    from collections import defaultdict
    by_year = defaultdict(list)
    for r in records:
        year = r['date'].year if r['date'] else 0
        by_year[year].append(r)

    total = len(records)
    years_sorted = sorted(by_year.keys())

    # ── Build sidebar navigation ───────────────────────────────────────────
    # Year jump links at top of sidebar
    year_jump_links = ' '.join(
        f'<a href="#year-{y}">{y if y else "?"}</a>' for y in years_sorted
    )

    # Per-release links grouped by year
    sidebar_html = ''
    release_index = 0
    for year in years_sorted:
        year_label = str(year) if year else 'Undated'
        sidebar_html += f'<div class="year-label" data-year="year-{year}">{year_label}</div>\n<ul>\n'
        for r in by_year[year]:
            anchor = f'release_{release_index}'
            r['_anchor'] = anchor  # stash for card rendering
            date_str = r['date'].strftime('%b %d, %Y') if r['date'] else 'Date unknown'
            safe_title = html_escape(r['title'])
            # Truncate long titles in sidebar to keep it scannable
            display_title = safe_title if len(safe_title) <= 60 else safe_title[:57] + '...'
            sidebar_html += (
                f'  <li>\n'
                f'    <a href="#{anchor}">{display_title}</a>\n'
                f'    <span class="index-date">{date_str}</span>\n'
                f'  </li>\n'
            )
            release_index += 1
        sidebar_html += '</ul>\n'

    # ── Build main content cards ───────────────────────────────────────────
    cards_html = ''
    for year in years_sorted:
        year_label = str(year) if year else 'Undated'
        year_id    = f'year-{year}'
        count      = len(by_year[year])
        cards_html += (
            f'<div class="year-group">'
            f'<div class="year-heading" id="{year_id}">'
            f'{year_label}<span class="count-badge">({count} release{"s" if count!=1 else ""})</span>'
            f'</div>\n'
        )
        for r in by_year[year]:
            warn_class = ' warning-card' if r['warnings'] else ''
            warn_tag   = ''.join(f'<span class="warning-tag">{html_escape(w)}</span>' for w in r['warnings'])

            date_str = r['date'].strftime('%B %d, %Y') if r['date'] else 'Date unknown'

            # Extract case number from filename for display
            case_m = CASE_RE.search(r['filename'])
            case_display = case_m.group(0) if case_m else ''

            body_html = body_to_html(r['body']) if r['body'] else '<p><em>No text extracted.</em></p>'

            pdf_url   = html_escape(r['pdf_link'])
            safe_title = html_escape(r['title'])
            anchor     = r['_anchor']
            aria_label = f"View original press release for {safe_title}, opens PDF in new tab"

            footer_html = format_footer_html(r['footer'])
            footer_bar  = f'  <div class="release-footer">{footer_html}</div>\n' if footer_html else ''

            cards_html += f"""<div class="release-card{warn_class}" id="{anchor}">
  <div class="release-header">
    <span class="release-title">{safe_title}{warn_tag}</span>
    <span class="release-date">{date_str}</span>
    <span class="release-case">{html_escape(case_display)}</span>
  </div>
  <div class="release-body">
{body_html}  </div>
{footer_bar}  <div class="pdf-link-bar">
    <a href="{pdf_url}"
       target="_blank"
       rel="noopener noreferrer"
       aria-label="{aria_label}"
       type="application/pdf">
      <svg aria-hidden="true" focusable="false" width="14" height="14" viewBox="0 0 24 24"
           fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
        <polyline points="14 2 14 8 20 8"/>
        <line x1="16" y1="13" x2="8" y2="13"/>
        <line x1="16" y1="17" x2="8" y2="17"/>
        <polyline points="10 9 9 9 8 9"/>
      </svg>
      View original PDF <span style="font-weight:normal;">(opens in new tab)</span>
    </a>
    <a href="#top" class="back-to-top">&uarr; Back to top</a>
  </div>
</div>
"""
        cards_html += '</div>\n'

    # ── Compute values needed for SEO tags ────────────────────────────────────
    real_years   = [y for y in years_sorted if y]
    year_min     = min(real_years) if real_years else 2004
    year_max     = max(real_years) if real_years else 2007
    page_url     = f"{BASE_URL}/"
    archive_url  = "https://info.sjpd.org/records/press_release_archive/"
    meta_desc    = (
        f"San Jose Police Department press releases {year_min}\u2013{year_max}. "
        f"{total} releases archived from original PDF records, covering homicides, "
        f"fatal traffic collisions, sexual assaults, missing persons, and community programs."
    )
    json_ld = f"""<script type="application/ld+json">
[
  {{
    "@context": "https://schema.org",
    "@type": "CollectionPage",
    "name": "SJPD Press Releases {year_min}\u2013{year_max}",
    "description": "{meta_desc}",
    "url": "{page_url}",
    "publisher": {{
      "@type": "GovernmentOrganization",
      "name": "San Jose Police Department",
      "url": "https://www.sjpd.org"
    }}
  }},
  {{
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    "itemListElement": [
      {{
        "@type": "ListItem",
        "position": 1,
        "name": "SJPD Press Release Archive",
        "item": "{archive_url}"
      }},
      {{
        "@type": "ListItem",
        "position": 2,
        "name": "{year_min}\u2013{year_max} Press Releases",
        "item": "{page_url}"
      }}
    ]
  }}
]
</script>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SJPD Press Releases {year_min}&ndash;{year_max} | San Jose Police Department Archive</title>
<meta name="description" content="{meta_desc}">
<link rel="canonical" href="{page_url}">
{json_ld}
<style>
{CSS}
</style>

</head>
<body>

<!-- WCAG 2.4.1 - Skip navigation link -->
<a class="skip-link" href="#main-content">Skip to main content</a>



<div class="page-header" id="top">
  <div class="page-header-text">
    <h1><a href="https://www.sjpd.org/about-us/inside-sjpd/press-releases" title="Jump to Current SJPD Press Releases">San Jose Police Department &mdash; Press Releases 2004&ndash;2007</a></h1>
    <p>{total} press releases &bull; Archived from original PDF records</p>
  </div>
  <p class="header-subtitle"><a href="https://www.sjpd.org/about-us/inside-sjpd/press-releases">&larr; View Current Press Releases</a></p>
</div>

<div class="wrapper">

  <!-- WCAG 1.3.1 - nav landmark with descriptive aria-label -->
  <nav class="sidebar" aria-label="Press releases index">
    <a class="back-link" href="../">&larr; Back to All Years</a>
    <h2>Press Releases</h2>   
    
    
    
    
    <div class="toc-years">Jump to: {year_jump_links}</div>
{sidebar_html}
  </nav>

  <!-- WCAG 1.3.1 - main landmark with id for skip link target -->
  <main class="content" id="main-content" aria-label="Press releases 2004 through 2007">
{cards_html}
  </main>

</div>

<div class="page-footer">
  <span>{FOOTER_CREDIT}</span>
  <span>{VERSION_LINE}</span>
</div>

<script>
document.querySelectorAll(".toc-years a").forEach(function(link) {{
  link.addEventListener("click", function() {{
    var yearId = this.getAttribute("href").substring(1);
    var sel = 'nav.sidebar .year-label[data-year="' + yearId + '"]';
    var sidebarLabel = document.querySelector(sel);
    if (sidebarLabel) {{
      sidebarLabel.scrollIntoView({{ block: "start" }});
    }}
  }});
}});
document.querySelectorAll(".back-to-top").forEach(function(link) {{
  link.addEventListener("click", function(e) {{
    e.preventDefault();
    window.scrollTo({{top: 0, behavior: 'smooth'}});
    var sidebar = document.querySelector("nav.sidebar");
    if (sidebar) {{
      sidebar.scrollTop = 0;
    }}
  }});
}});
</script>
<script src="page-search.js"></script>
</body>
</html>
"""
    return html

# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    pdf_dir = Path(PDF_DIR)
    pdf_files = sorted(pdf_dir.glob("*.pdf"), key=lambda p: p.name.lower())

    if not pdf_files:
        print(f"No PDF files found in {PDF_DIR}")
        sys.exit(1)

    print(f"Found {len(pdf_files)} PDF files. Processing...")
    records = []
    warnings_summary = []

    for i, pdf_path in enumerate(pdf_files, 1):
        print(f"  [{i:3d}/{len(pdf_files)}] {pdf_path.name[:60]}", end='')
        r = process_pdf(pdf_path)
        records.append(r)
        date_str = r['date'].strftime('%Y-%m-%d') if r['date'] else 'NO DATE'
        src = f"({r['date_source']})" if r['date'] else ''
        warn = ' *** ' + ', '.join(r['warnings']) if r['warnings'] else ''
        print(f"  -> {date_str} {src}{warn}")
        if r['warnings']:
            warnings_summary.append((pdf_path.name, r['warnings']))

    print(f"\nBuilding HTML ({len(records)} records)...")
    html = build_html(records)

    out_path = Path(OUTPUT_FILE)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding='utf-8')
    print(f"Written: {OUTPUT_FILE}")

    if warnings_summary:
        print(f"\n{'='*60}")
        print(f"FILES NEEDING REVIEW ({len(warnings_summary)}):")
        for fname, warns in warnings_summary:
            print(f"  {fname}: {', '.join(warns)}")

    print(f"\nDone. {len(records)} press releases archived.")

if __name__ == '__main__':
    main()
