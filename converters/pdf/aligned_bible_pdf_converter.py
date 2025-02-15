#!/usr/bin/env python3
#
#  Copyright (c) 2020 unfoldingWord
#  http://creativecommons.org/licenses/MIT/
#  See LICENSE file for details.
#
#  Contributors:
#  Richard Mahn <rich.mahn@unfoldingword.org>

"""
This script generates the HTML and PDF for a given Bible
"""
import os
import re
from bs4 import BeautifulSoup
from .pdf_converter import PdfConverter
from door43_tools.bible_books import BOOK_NUMBERS
from general_tools.file_utils import read_file
from general_tools.usfm_utils import unalign_usfm
from tx_usfm_tools.singleFilelessHtmlRenderer import SingleFilelessHtmlRenderer
from door43_tools.subjects import ALIGNED_BIBLE

PROJECT_FULL = 'full' # Single PDF for the full bible 

class AlignedBiblePdfConverter(PdfConverter):
    my_subject = ALIGNED_BIBLE

    def __init__(self, *args, **kwargs):
        self.chapter = None
        self.chapters = []
        super().__init__(*args, **kwargs)

    def get_sample_text(self):
        return "REPLACE THIS"

    @property
    def book_number(self):
        if self.project_id and self.project_id in BOOK_NUMBERS:
            return BOOK_NUMBERS[self.project_id]

    @staticmethod
    def parse_chapters(chapter):
        chapters = []
        if chapter:
            comma_nums = chapter.split(',')
            for nums in comma_nums:
                dash_nums = nums.split('-')
                start_num = int(dash_nums[0])
                if len(dash_nums) > 1:
                    end_num = int(dash_nums[-1]) + 1
                else:
                    end_num = start_num + 1
                for num in range(start_num, end_num):
                    chapters.append(num)
        return chapters

    @property
    def file_id_project_str(self):
        if self.project_id and self.project_id != PROJECT_FULL:
            return super().file_id_project_str.upper()
        else:
            return ''

    @property
    def project_title(self):
        if self.project_id == PROJECT_FULL:
            return ''
        else:
            if self.project:
                return self.project['title']

    def get_appendix_rcs(self):
        pass

    def replace_rc_links(self, text):
        return text

    def get_default_project_ids(self):
        return [PROJECT_FULL] + list(map(lambda project: project['identifier'], self.main_resource.projects))

    def get_body_html(self):
        self.log.info('Creating Bible for {0}...'.format(self.file_project_and_ref))
        self.add_style_sheet('../css/bible_style.css')
        return self.get_bible_html()

    def get_book_title(self, project):
        if self.main_resource.title in project['title']:
            return project['title'].replace(f' {self.main_resource.title}', '')
        else:
            return project['title'].replace(f' {self.main_resource.simple_title}', '')

    def get_bible_html(self):
        if not self.project_id:
            self.project_id = PROJECT_FULL
        if self.project_id == PROJECT_FULL:
            projects = self.main_resource.projects
        else:
            projects = [self.main_resource.find_project(self.project_id)]
        bible_html = f'''
<section id="{self.language_id}-{self.name}" class="bible {self.name}-bible bible-{self.project_id} {self.name}-bible-{self.project_id}">
'''
        for project in projects:
            project_id = project['identifier']
            if project_id not in BOOK_NUMBERS:
                continue
            project_num = BOOK_NUMBERS[project_id]
            project_file = os.path.join(self.main_resource.repo_dir, f'{project_num}-{project_id.upper()}.usfm')
            usfm = read_file(project_file)
            usfm = unalign_usfm(usfm)
            if self.chapters:
                usfm_split = re.split(r'\\c ', usfm)
                usfm = usfm_split[0]
                for chapter in self.chapters:
                    usfm += '\\c ' + usfm_split[chapter]
            self.log.info(f'Converting {project_id.upper()} from USFM to HTML...')
            html, warnings = SingleFilelessHtmlRenderer({project_id.upper(): usfm}).render()
            soup = BeautifulSoup(html, 'html.parser')
            book_header = soup.find('h1')
            book_title = book_header.text
            book_header['class'] = book_header.get('class', []) + ['section-header']
            book_header['header_title'] = self.title
            chapter_headers = soup.find_all('h2')
            for chapter_header in chapter_headers:
                chapter_title = chapter_header.text
                header_title = book_title
                chapter = ''
                if chapter_title:
                    search = re.search(r'\d+', chapter_title)
                    if search:
                        chapter = search.group()
                        if chapter:
                            header_title = f'{book_title} {chapter}'
                classes = ['section-header']
                if len(projects) > 1:
                    classes += ['no-toc']
                chapter_header['class'] = chapter_header.get('class', []) + classes
                chapter_header['id'] = f'{self.language_id}-{self.name}-{project_id}-{self.pad(chapter)}'
                chapter_header['header_title'] = header_title
            article_html = ''.join(['%s' % x for x in soup.body.contents]).strip()
            bible_html += f'''
    <article id="{self.language_id}-{self.name}-{project_id}" class="bible-book bible-book-{project_id} {self.name}-bible-book">
        <div class="bible-book-wrapper">
            {article_html}
        </div>
    </article>
'''
        bible_html += '''
</section>
'''
        return bible_html

    def fix_links(self, html):
        html = re.sub(r' +(<span id="ref-fn-)', r'\1', html, flags=re.MULTILINE)
        html = re.sub(r'(</b></sup></span>) +', r'\1', html, flags=re.MULTILINE)
        html = re.sub(r' +(</i>)', r'\1', html, flags=re.MULTILINE)
        return html
