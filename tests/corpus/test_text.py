import unittest

from corpus.text import extract_document


def article(body):
    return '<h1 id="firstHeading">Название</h1><div id="mw-content-text"><div class="mw-parser-output">' + body + '</div></div>'


class TextTests(unittest.TestCase):
    def test_inline_formatting_and_spaces(self):
        title, text = extract_document(article('<p>кино<b>театр</b> и <i>кино</i> рядом</p>'))
        self.assertEqual(title, 'Название')
        self.assertEqual(text, 'кинотеатр и кино рядом')

    def test_blocks_quotes_lists_and_captions(self):
        _, text = extract_document(article(
            '<h2>Сюжет</h2><p>Первый</p><p>Второй<br>Третий</p>'
            '<blockquote>Цитата</blockquote><ul><li>Один</li><li>Два</li></ul>'
            '<figure><img src="x"><figcaption>Подпись</figcaption></figure>'
        ))
        self.assertEqual(text.splitlines(), ['Сюжет', 'Первый', 'Второй', 'Третий', 'Цитата', 'Один', 'Два', 'Подпись'])

    def test_noise_and_references(self):
        _, text = extract_document(article(
            '<script>script</script><style>style</style><noscript>noise</noscript>'
            '<div class="toc">contents</div><div class="hatnote">note</div>'
            '<span class="mw-editsection">edit</span><div class="noprint">print</div>'
            '<p>Текст<sup class="reference">[1]</sup>.</p>'
            '<div class="reflist"><ol class="references"><li>reference</li></ol></div>'
            '<!-- hidden -->'
        ))
        self.assertEqual(text, 'Текст.')

    def test_useful_table_survives(self):
        _, text = extract_document(article(
            '<table class="navbox"><tr><td>Навигация</td></tr></table>'
            '<table class="infobox"><tr><th>Год</th><td>1999</td></tr>'
            '<tr><th>Режиссёр</th><td>Имя</td></tr></table>'
        ))
        self.assertEqual(text, 'Год 1999\nРежиссёр Имя')

    def test_entities_and_case(self):
        _, text = extract_document(article('<p>Ёлки&nbsp; &amp; &lt;ЕЖИ&gt; &#169; 2020</p>'))
        self.assertEqual(text, 'Ёлки & <ЕЖИ> © 2020')

    def test_fallbacks(self):
        self.assertEqual(extract_document('<title>Заголовок — сайт</title><div class="mw-parser-output">Текст</div>'), ('Заголовок — сайт', 'Текст'))
        self.assertEqual(extract_document('<div class="mw-parser-output">Текст</div>'), ('', 'Текст'))

    def test_missing_or_empty_content(self):
        for html in ('<p>captcha</p>', article(' \n '), article('<script>noise</script>')):
            with self.subTest(html=html), self.assertRaises(ValueError):
                extract_document(html)


if __name__ == '__main__':
    unittest.main()
