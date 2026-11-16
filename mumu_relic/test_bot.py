import unittest
from bot import decide

class Decisions(unittest.TestCase):
    def boss(self, percent, confidence=.727):
        return [('战斗', .522, .729, .774), ('撤离', .648, .25, .774),
                ('我方胜率', .775, .63, .875),
                (percent, confidence, .84, .875)]

    def test_base_rate_boundary_ignores_bonus(self):
        for text, expected in [('29% + 8%', ('撤离',29)),
                               ('30% + 5%', ('战斗',30)),
                               ('45% + 5%', ('战斗',45)),
                               ('90% + 5%', ('战斗',90))]:
            with self.subTest(text=text):
                self.assertEqual(decide(self.boss(text))[:2], expected)

    def test_no_guess_on_incomplete_or_uncertain_rate(self):
        for rows in [self.boss('+5%'), self.boss('4S%+5%'),
                     self.boss('45%+5%', .6), self.boss('45%+5%')[0:2],
                     [r for r in self.boss('45%+5%') if '胜率' not in r[0]]]:
            self.assertIsNone(decide(rows))

    def test_forward_needs_title_and_position(self):
        title=('探险第2层',.743,.5,.04)
        self.assertEqual(decide([title,('前进',.518,.504,.863)])[0], '前进')
        self.assertIsNone(decide([('前进',.518,.504,.863)]))
        self.assertIsNone(decide([title,('前进',.518,.1,.863)]))

    def test_home(self):
        self.assertEqual(decide([('遗迹探险',.794,.5,.04),
                                 ('万去探险!',.608,.553,.854)])[0], '去探险')

    def test_collect_needs_end_title(self):
        collect=('收下',.7,.5,.94)
        self.assertEqual(decide([('探险结束',.8,.5,.07),collect])[0], '收下')
        self.assertIsNone(decide([collect]))

    def test_reward_overlay_has_priority(self):
        rows=[('探险第2层',.743,.5,.04),('前进',.6,.5,.863),
              ('点击任意位置继续',.65,.5,.925)]
        self.assertEqual(decide(rows), ('关闭宝物展示',None,.5,.5))

if __name__ == '__main__':
    unittest.main()
