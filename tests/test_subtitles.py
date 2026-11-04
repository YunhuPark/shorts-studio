import unittest

from shorts_studio.render.subtitles import clean, split_phrases


class SplitPhrases(unittest.TestCase):
    def test_number_and_counter_stay_together(self):
        # regression: was split as "저기, 오늘은 두" / "개네요?"
        self.assertEqual(split_phrases("저기, 오늘은 두 개네요?"), ["저기 오늘은 두 개네요?"])

    def test_numeral_is_not_left_alone_at_the_end_of_a_phrase(self):
        # without the numeral rule this line splits as "... 몫으로 두" / "개를 샀다는 말이었다"
        chunks = split_phrases("결혼기념일이라서 집사람 몫으로 두 개를 샀다는 말이었다")
        self.assertIn("집사람 몫으로 두 개를", chunks)
        self.assertFalse(any(c.endswith(" 두") or c == "두" for c in chunks), chunks)

    def test_no_trailing_period_or_comma(self):
        for line in ["새벽 3시. 비 오는 날의 편의점.", "그래서 대신, 뜨거운 물을 두 컵 부었다.", "…고맙네."]:
            for phrase in split_phrases(line):
                self.assertFalse(phrase.endswith((".", ",")), phrase)
                self.assertNotIn(".", phrase)
                self.assertNotIn(",", phrase)

    def test_modifier_stays_with_noun(self):
        for phrase in split_phrases("하얀 머리에 낡은 모자를 쓴 할아버지."):
            self.assertFalse(phrase.endswith("낡은"), phrase)
        for phrase in split_phrases("그래서 대신, 뜨거운 물을 두 컵 부었다."):
            self.assertFalse(phrase.endswith("뜨거운"), phrase)

    def test_sentences_split_first(self):
        self.assertEqual(split_phrases("새벽 3시. 비 오는 날의 편의점."), ["새벽 3시", "비 오는 날의 편의점"])

    def test_phrase_length_is_bounded(self):
        lines = ["다음 날에도, 그다음 날에도, 나는 3시를 기다렸다.", "그래서 오늘도 나는, 컵라면 두 개에 물을 붓는다."]
        for line in lines:
            for phrase in split_phrases(line):
                self.assertLessEqual(len(phrase), 17, phrase)

    def test_question_mark_is_kept(self):
        self.assertTrue(split_phrases("저기, 오늘은 두 개네요?")[-1].endswith("?"))

    def test_text_is_preserved_apart_from_punctuation(self):
        line = "그래서 오늘도 나는, 컵라면 두 개에 물을 붓는다."
        self.assertEqual(" ".join(split_phrases(line)), clean(line))

    def test_empty(self):
        self.assertEqual(split_phrases(""), [])


if __name__ == "__main__":
    unittest.main()
