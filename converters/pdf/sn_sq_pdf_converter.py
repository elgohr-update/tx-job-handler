#!/usr/bin/env python3
#
#  Copyright (c) 2020 unfoldingWord
#  http://creativecommons.org/licenses/MIT/
#  See LICENSE file for details.
#
#  Contributors:
#  Richard Mahn <rich.mahn@unfoldingword.org>

"""
This script generates the HTML and PDF SN-SQ documents
"""
import os
import re
import markdown2
import general_tools.html_tools as html_tools
from collections import OrderedDict
from .tsv_pdf_converter import TsvPdfConverter
from door43_tools.bible_books import BOOK_CHAPTER_VERSES
from general_tools.alignment_tools import get_alignment, flatten_alignment, flatten_quote

QUOTES_TO_IGNORE = ['general information:', 'connecting statement:']


class SnSqPdfConverter(TsvPdfConverter):
    required_resources = ['sn', 'sq']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sn_book_data = OrderedDict()
        self.sq_book_data = OrderedDict()

    @property
    def name(self):
        return 'sn-sq'

    @property
    def title(self):
        sn_title = self.resources['sn'].title
        sq_title = self.resources['sq'].title
        return f'{sn_title}\n<br/>\n&\n<br/>\n{sq_title}'

    @property
    def simple_title(self):
        sn_title = self.resources['sn'].simple_title
        sq_title = self.resources['sq'].simple_title
        return f'{sn_title} & {sq_title}'

    def get_appendix_rcs(self):
        return

    def get_body_html(self):
        self.log.info('Creating SN for {0}...'.format(self.file_project_and_ref))
        self.process_bibles()
        for bible in self.alignment_bibles:
            self.populate_book_data(bible.idenitifer)
        self.populate_book_data(self.ol_bible_id, self.ol_lang_code)
        self.populate_sn_book_data()
        self.populate_sq_book_data()
        html = self.get_sn_sq_html()
        self.sn_book_data = None
        return html

    def populate_sn_book_data(self):
        book_filename = f'{self.language_id}_{self.resources["sn"].resource_name}_{self.book_number}-{self.project_id.upper()}.tsv'
        book_filepath = os.path.join(self.resources['sn'].repo_dir, book_filename)
        if not os.path.isfile(book_filepath):
            return
        book_data = OrderedDict()
        reader = self.unicode_csv_reader(open(book_filepath))
        header = next(reader)
        row_count = 1
        for row in reader:
            row_count += 1
            verse_data = {
                'contextId': None,
                'row': row_count,
                'alignments': {}
            }
            for bible in self.alignment_bibles:
                verse_data['alignments'][bible.identifier] = None
            found = False
            for idx, field in enumerate(header):
                field = field.strip()
                if idx >= len(row):
                    self.log.error(f'ERROR: {book_filepath} is malformed at row {row_count}: {row}')
                    self.add_error_message(self.create_rc(f'{book_filename}#{row_count}'), f'Line {row_count}', f'Malformed row: {row}')
                    found = False
                    break
                else:
                    found = True
                    verse_data[field] = row[idx]
            if not found:
                continue
            chapter = verse_data['Chapter'].lstrip('0')
            verse = verse_data['Verse'].lstrip('0')
            if verse_data['Occurrence']:
                occurrence = int(verse_data['Occurrence'])
            else:
                occurrence = 1
            sn_rc_link = f'rc://{self.language_id}/sn/help/{self.project_id}/{self.pad(chapter)}/{verse.zfill(3)}/{verse_data["ID"]}'
            sn_title = f'{verse_data["GLQuote"]}'
            if verse_data['OrigQuote']:
                context_id = None
                if not context_id and chapter.isdigit() and verse.isdigit():
                    context_id = {
                        'reference': {
                            'chapter': int(chapter),
                            'verse': int(verse)
                        },
                        'rc': f'rc://{self.language_id}/sn/help///{self.project_id}/{self.pad(chapter)}/{verse.zfill(3)}',
                        'quote': verse_data['OrigQuote'],
                        'occurrence': occurrence,
                        'quoteString': verse_data['OrigQuote']
                    }
                if context_id:
                    context_id['rc'] += f'/{verse_data["ID"]}'
                    context_id['quoteString'] = verse_data['OrigQuote']
                    verse_data['contextId'] = context_id
                    verse_data['alignments'] = {}
                    for bible in self.alignment_bibles:
                        verse_data['alignments'][bible.identifier] = self.get_aligned_text(bible.identifier, context_id)
                if verse_data['alignments'][self.ult]:
                    sn_title = flatten_alignment(verse_data['alignments'][self.ult]) + f' ({self.ult.upper()})'
                    if verse_data['alignments'][self.ust]:
                        sn_title += '<br/>' + flatten_alignment(verse_data['alignments'][self.ust]) + f' ({self.ust.upper()})'
                else:
                    sn_title = f'{verse_data["GLQuote"]}'
            sn_rc = self.create_rc(sn_rc_link, title=sn_title)
            verse_data['title'] = sn_title
            verse_data['rc'] = sn_rc
            if chapter not in book_data:
                book_data[chapter] = OrderedDict()
            if verse not in book_data[chapter]:
                book_data[chapter][verse] = []
            book_data[str(chapter)][str(verse)].append(verse_data)
        self.sn_book_data = book_data

    def populate_sq_book_data(self):
        book_filename = f'{self.language_id}_{self.resources["sq"].resource_name}_{self.book_number}-{self.project_id.upper()}.tsv'
        book_filepath = os.path.join(self.resources['sq'].repo_dir, book_filename)
        if not os.path.isfile(book_filepath):
            return
        book_data = OrderedDict()
        reader = self.unicode_csv_reader(open(book_filepath))
        header = next(reader)
        row_count = 1
        for row in reader:
            row_count += 1
            verse_data = {
                'contextId': None,
                'row': row_count,
                'alignments': {
                    self.ult: None,
                    self.ust: None
                }
            }
            found = False
            for idx, field in enumerate(header):
                field = field.strip()
                if idx >= len(row):
                    self.log.error(f'ERROR: {book_filepath} is malformed at row {row_count}: {row}')
                    self.add_error_message(self.create_rc(f'{book_filename}#{row_count}'), f'Line {row_count}', f'Malformed row: {row}')
                    found = False
                    break
                else:
                    found = True
                    verse_data[field] = row[idx]
            if not found:
                continue
            chapter = verse_data['Chapter'].lstrip('0')
            verse = verse_data['Verse'].lstrip('0')
            if verse_data['Occurrence']:
                occurrence = int(verse_data['Occurrence'])
            else:
                occurrence = 1
            sq_rc_link = f'rc://{self.language_id}/sq/help/{self.project_id}/{self.pad(chapter)}/{verse.zfill(3)}/{verse_data["ID"]}'
            sq_title = f'{verse_data["GLQuote"]}'
            if verse_data['OrigQuote']:
                context_id = None
                if not context_id and chapter.isdigit() and verse.isdigit():
                    context_id = {
                        'reference': {
                            'chapter': int(chapter),
                            'verse': int(verse)
                        },
                        'rc': f'rc://{self.language_id}/sq/help///{self.project_id}/{self.pad(chapter)}/{verse.zfill(3)}',
                        'quote': verse_data['OrigQuote'],
                        'occurrence': occurrence,
                        'quoteString': verse_data['OrigQuote']
                    }
                if context_id:
                    context_id['rc'] += f'/{verse_data["ID"]}'
                    context_id['quoteString'] = verse_data['OrigQuote']
                    verse_data['contextId'] = context_id
                    verse_data['alignments'] = {
                        self.ult: self.get_aligned_text(self.ult, context_id),
                        self.ust: self.get_aligned_text(self.ust, context_id)
                    }
                if verse_data['alignments'][self.ult]:
                    sq_title = flatten_alignment(verse_data['alignments'][self.ult]) + f' ({self.ult.upper()})'
                    if verse_data['alignments'][self.ust]:
                        sq_title += '<br/>' + flatten_alignment(verse_data['alignments'][self.ust]) + f' ({self.ust.upper()})'
                else:
                    sq_title = f'{verse_data["GLQuote"]}'
            sq_rc = self.create_rc(sq_rc_link, title=sq_title)
            verse_data['title'] = sq_title
            verse_data['rc'] = sq_rc
            if chapter not in book_data:
                book_data[chapter] = OrderedDict()
            if verse not in book_data[chapter]:
                book_data[chapter][verse] = []
            book_data[str(chapter)][str(verse)].append(verse_data)
        self.sq_book_data = book_data

    def get_sn_sq_html(self):
        sn_html = f'''
<section id="{self.language_id}-{self.name}-{self.project_id}" class="{self.name}">
    <h1 class="section-header hidden">{self.simple_title}</h1>
        <h2 class="section-header">{self.project_title}</h2>
'''
        if 'front' in self.sn_book_data and 'intro' in self.sn_book_data['front']:
            book_intro = markdown2.markdown(self.sn_book_data['front']['intro'][0]['OccurrenceNote'].replace('<br>', '\n'))
            book_intro_title = html_tools.get_title_from_html(book_intro)
            book_intro = self.fix_sn_links(book_intro, 'intro')
            book_intro = html_tools.make_first_header_section_header(book_intro, level=3)
            # HANDLE FRONT INTRO RC LINKS
            book_intro_rc_link = f'rc://{self.language_id}/sn/help/{self.project_id}/front/intro'
            book_intro_rc = self.add_rc(book_intro_rc_link, title=book_intro_title)
            book_intro = f'''
    <article id="{book_intro_rc.article_id}">
        {book_intro}
    </article>
'''
            book_intro_rc.set_article(book_intro)
            sn_html += book_intro

        if 'front' in self.sq_book_data and 'intro' in self.sq_book_data['front']:
            book_intro = markdown2.markdown(self.sq_book_data['front']['intro'][0]['OccurrenceNote'].replace('<br>', '\n'))
            book_intro_title = html_tools.get_title_from_html(book_intro)
            book_intro = self.fix_tsv_links(book_intro, 'intro')
            book_intro = html_tools.make_first_header_section_header(book_intro, level=3)
            # HANDLE FRONT INTRO RC LINKS
            book_intro_rc_link = f'rc://{self.language_id}/sq/help/{self.project_id}/front/intro'
            book_intro_rc = self.add_rc(book_intro_rc_link, title=book_intro_title)
            book_intro = f'''
    <article id="{book_intro_rc.article_id}">
        {book_intro}
    </article>
'''
            book_intro_rc.set_article(book_intro)
            sn_html += book_intro

        for chapter in BOOK_CHAPTER_VERSES[self.project_id]:
            self.log.info(f'Chapter {chapter}...')
            chapter_title = f'{self.project_title} {chapter}'
            # HANDLE INTRO RC LINK
            sn_chapter_rc_link = f'rc://{self.language_id}/sn/help/{self.project_id}/{self.pad(chapter)}'
            sn_chapter_rc = self.add_rc(sn_chapter_rc_link, title=chapter_title)
            sq_chapter_rc_link = f'rc://{self.language_id}/sq/help/{self.project_id}/{self.pad(chapter)}'
            sq_chapter_rc = self.add_rc(sq_chapter_rc_link, title=chapter_title)
            sn_html += f'''
    <section id="{sn_chapter_rc.article_id}" class="chapter">
        <h3 class="section-header" header-level="2">{chapter_title}</h3>
'''
            if 'intro' in self.sn_book_data[chapter]:
                self.log.info('Generating SN chapter info...')
                chapter_intro = markdown2.markdown(self.sn_book_data[chapter]['intro'][0]['OccurrenceNote'].replace('<br>', "\n"))
                # Remove leading 0 from chapter header
                chapter_intro = re.sub(r'<h(\d)>([^>]+) 0+([1-9])', r'<h\1>\2 \3', chapter_intro, 1, flags=re.MULTILINE | re.IGNORECASE)
                chapter_intro = html_tools.make_first_header_section_header(chapter_intro, level=4, no_toc=True, header_level=3)
                chapter_intro_title = html_tools.get_title_from_html(chapter_intro)
                chapter_intro = self.fix_sn_links(chapter_intro, chapter)
                # HANDLE INTRO RC LINK
                chapter_intro_rc_link = f'rc://{self.language_id}/sn/help/{self.project_id}/{self.pad(chapter)}/intro'
                chapter_intro_rc = self.add_rc(chapter_intro_rc_link, title=chapter_intro_title)
                chapter_intro = f'''
        <article id="{chapter_intro_rc.article_id}">
            {chapter_intro}
        </article>
'''
                chapter_intro_rc.set_article(chapter_intro)
                sn_html += chapter_intro

            if 'intro' in self.sq_book_data[chapter]:
                self.log.info('Generating SQ chapter info...')
                chapter_intro = markdown2.markdown(self.sq_book_data[chapter]['intro'][0]['OccurrenceNote'].replace('<br>', "\n"))
                # Remove leading 0 from chapter header
                chapter_intro = re.sub(r'<h(\d)>([^>]+) 0+([1-9])', r'<h\1>\2 \3', chapter_intro, 1, flags=re.MULTILINE | re.IGNORECASE)
                chapter_intro = html_tools.make_first_header_section_header(chapter_intro, level=4, no_toc=True, header_level=3)
                chapter_intro_title = html_tools.get_title_from_html(chapter_intro)
                chapter_intro = self.fix_sn_links(chapter_intro, chapter)
                # HANDLE INTRO RC LINK
                chapter_intro_rc_link = f'rc://{self.language_id}/sq/help/{self.project_id}/{self.pad(chapter)}/intro'
                chapter_intro_rc = self.add_rc(chapter_intro_rc_link, title=chapter_intro_title)
                chapter_intro = f'''
        <article id="{chapter_intro_rc.article_id}">
            {chapter_intro}
        </article>
'''
                chapter_intro_rc.set_article(chapter_intro)
                sn_html += chapter_intro

            for verse in range(1,  int(BOOK_CHAPTER_VERSES[self.project_id][chapter]) + 1):
                verse = str(verse)
                self.log.info(f'Generating verse {chapter}:{verse}...')
                sn_html += self.get_sn_sq_article(chapter, verse)
            sn_html += '''
    </section>
'''
        sn_html += '''
</section>
'''
        self.log.info('Done generating SN HTML.')
        return sn_html

    def get_sn_sq_article(self, chapter, verse):
        sn_title = f'{self.project_title} {chapter}:{verse}'
        sn_rc_link = f'rc://{self.language_id}/sn/help/{self.project_id}/{self.pad(chapter)}/{verse.zfill(3)}'
        sn_rc = self.add_rc(sn_rc_link, title=sn_title)
        sq_rc_link = f'rc://{self.language_id}/sq/help/{self.project_id}/{self.pad(chapter)}/{verse.zfill(3)}'
        sq_rc = self.add_rc(sq_rc_link, title=sn_title)
        ult_text = self.get_plain_scripture(self.ult, chapter, verse)
        ult_text = self.get_scripture_with_sn_quotes(self.ult, chapter, verse, self.create_rc(f'rc://{self.language_id}/ult/bible/{self.project_id}/{chapter}/{verse}', ult_text), ult_text)
        ust_text = self.get_plain_scripture(self.ust, chapter, verse)
        ust_text = self.get_scripture_with_sn_quotes(self.ust, chapter, verse, self.create_rc(f'rc://{self.language_id}/ust/bible/{self.project_id}/{chapter}/{verse}', ult_text), ust_text)

        sn_article = f'''
                <article id="{sn_rc.article_id}">
                    <h4 class="section-header no-toc" header-level="2">{sn_title}</h4>
                    <div class="notes">
                            <div class="col1">
                                <h3 class="bible-resource-title">{self.ult.upper()}</h3>
                                <div class="bible-text">{ult_text}</div>
                                <h3 class="bible-resource-title">{self.ust.upper()}</h3>
                                <div class="bible-text">{ust_text}</div>
                            </div>
                            <div class="col2">
                                <div class="study-notes">
                                    <h5>{self.translate("study_notes")}</h5>
                                    {self.get_sn_article_text(chapter, verse)}
                                </div>
                                <div class="study-questions">
                                    <h5>{self.translate("study_questions")}</h5>
                                    {self.get_sq_article_text(chapter, verse)}
                                </div>
                            </div>
                    </div>
                </article>
'''
        sn_rc.set_article(sn_article)
        return sn_article

    def get_sn_article_text(self, chapter, verse):
        verse_notes = ''
        if verse in self.sn_book_data[chapter]:
            for sn_note in self.sn_book_data[chapter][verse]:
                note = markdown2.markdown(sn_note['OccurrenceNote'].replace('<br>', "\n"))
                note = re.sub(r'</*p[^>]*>', '', note, flags=re.IGNORECASE | re.MULTILINE)
                verse_notes += f'''
        <div id="{sn_note['rc'].article_id}" class="verse-note">
            <h6 class="verse-note-title">{sn_note['title']}</h6>
            <div class="verse-note-text">
                {note}
            </div>
        </div>
'''
        else:
            verse_notes += f'''
        <div class="no-notes">
            ({self.translate('no_notes_for_this_verse')})
        </div>
'''
        verse_notes = self.fix_sn_links(verse_notes, chapter)
        return verse_notes

    def get_sq_article_text(self, chapter, verse):
        verse_questions = ''
        if verse in self.sn_book_data[chapter]:
            for sq_question in self.sq_book_data[chapter][verse]:
                question = markdown2.markdown(sq_question['OccurrenceNote'].replace('<br>', "\n"))
                question = re.sub(r'</*p[^>]*>', '', question, flags=re.IGNORECASE | re.MULTILINE)
                verse_questions += f'''
        <div id="{sq_question['rc'].article_id}" class="verse-question">
            <div class="verse-question-text">
                {question}
            </div>
        </div>
'''
        else:
            verse_questions += f'''
        <div class="no-questions">
            ({self.translate('no_questions_for_this_verse')})
        </div>
'''
        verse_questions = self.fix_sn_links(verse_questions, chapter)
        return verse_questions

    def get_scripture_with_sn_quotes(self, bible_id, chapter, verse, rc, scripture):
        if not scripture:
            scripture = self.get_plain_scripture(bible_id, chapter, verse)
        footnotes_split = re.compile('<div class="footnotes">', flags=re.IGNORECASE | re.MULTILINE)
        verses_and_footnotes = re.split(footnotes_split, scripture, maxsplit=1)
        scripture = verses_and_footnotes[0]
        footnote = ''
        if len(verses_and_footnotes) == 2:
            footnote = f'<div class="footnotes">{verses_and_footnotes[1]}'
        if verse in self.sn_book_data[chapter]:
            sn_notes = self.sn_book_data[chapter][verse]
        else:
            sn_notes = []
        orig_scripture = scripture
        for sn_note_idx, sn_note in enumerate(sn_notes):
            occurrence = 1
            if represent_int(sn_note['Occurrence']) and int(sn_note['Occurrence']) > 0:
                occurrence = int(sn_note['Occurrence'])
            gl_quote_phrase = [[{
                'word': sn_note['GLQuote'],
                'occurrence': occurrence
            }]]
            phrase = sn_note['alignments'][bible_id]
            if not phrase:
                phrase = gl_quote_phrase
            if flatten_alignment(phrase).lower() in QUOTES_TO_IGNORE:
                continue
            split = ''
            if len(phrase) > 1:
                split = ' split'
            tag = f'<span class="highlight phrase phrase-{sn_note_idx+1}{split}">'
            marked_verse_html = html_tools.mark_phrases_in_html(scripture, phrase, tag=tag)
            if not marked_verse_html:
                fix = None
                if flatten_alignment(phrase).lower() not in QUOTES_TO_IGNORE:
                    if sn_note['GLQuote']:
                        marked_with_gl_quote = html_tools.mark_phrases_in_html(scripture, gl_quote_phrase)
                        if marked_with_gl_quote:
                            fix = sn_note['GLQuote']
                    self.add_bad_highlight(rc, orig_scripture, sn_note['rc'], sn_note['GLQuote'], fix)
            else:
                scripture = marked_verse_html
        scripture += footnote
        return scripture

    def get_aligned_text(self, bible_id, context_id):
        if not context_id or 'quote' not in context_id or not context_id['quote'] or 'reference' not in context_id or \
                'chapter' not in context_id['reference'] or 'verse' not in context_id['reference']:
            return None
        chapter = str(context_id['reference']['chapter'])
        verse = str(context_id['reference']['verse'])
        verse_objects = self.get_verse_objects(bible_id, chapter, verse)
        if not verse_objects:
            return None
        quote = context_id['quote']
        occurrence = int(context_id['occurrence'])
        alignment = get_alignment(verse_objects, quote, occurrence)
        if not alignment:
            title = f'{self.project_title} {chapter}:{verse}'
            aligned_text_rc_link = f'rc://{self.language_id}/{bible_id}/bible/{self.project_id}/{self.pad(chapter)}/{str(verse).zfill(3)}'
            aligned_text_rc = self.create_rc(aligned_text_rc_link, title=title)
            if 'quoteString' in context_id:
                quote_string = context_id['quoteString']
            else:
                quote_string = context_id['quote']
                if isinstance(quote_string, list):
                    flatten_quote(context_id['quote'])
            if int(self.book_number) > 40 or self.project_id.lower() == 'rut' or self.project_id.lower() == 'jon':
                title = f'OL ({self.ol_lang_code.upper()}) quote not found in {bible_id.upper()} {self.project_title} {chapter}:{verse} alignment'
                message = f'''
VERSE: {self.project_title} {chapter}:{verse}
RC: {context_id['rc']}
QUOTE: {quote_string}
{bible_id.upper()}: {self.book_data[bible_id][chapter][verse]['usfm']}
{self.ol_bible_id.upper()}: {self.book_data[self.ol_bible_id][chapter][verse]['usfm']}
'''
                self.add_error_message(self.create_rc(context_id['rc']), title, message)
        return alignment

    def fix_sn_links(self, html, chapter):
        html = self.fix_tsv_links(html, chapter)
        return html
