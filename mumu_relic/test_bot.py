import unittest
from bot import decide, image_forward_action, wait_for_resume, wait_with_controls
from unittest.mock import patch

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

    def test_low_confidence_split_label_from_floor_10(self):
        # Text/confidences are from the user log; coordinates model the
        # established layout because this log did not include coordinates.
        rows = [('撤离', .648, .25, .774), ('战斗', .64, .729, .774),
                ('我方胜率', .662, .63, .875),
                ('40% + 8%', .705, .84, .875)]
        self.assertEqual(decide(rows)[:2], ('战斗', 40))
        rows[2] = ('我方胜率', .59, .63, .875)
        self.assertIsNone(decide(rows))
        rows[2] = ('我方胜率', .662, .63, .70)
        self.assertIsNone(decide(rows))

    def test_image_fallback_when_forward_text_is_missing(self):
        from PIL import Image, ImageDraw
        image = Image.new('RGB', (450, 800), '#b29661')
        draw = ImageDraw.Draw(image)
        cx, cy, radius = 225, 656, 74
        draw.ellipse((cx-radius, cy-radius, cx+radius, cy+radius),
                     fill='#15ca85', outline='black', width=4)
        draw.rectangle((cx-8, cy-22, cx+8, cy+14), fill='#ff9814')
        # The word on the button is deliberately absent.
        rows = [('探险第2层', .753, .50, .04), ('5倍场', .578, .50, .08)]
        self.assertIsNone(decide(rows))
        self.assertEqual(image_forward_action(rows, image)[:2], ('前进', None))
        self.assertIsNone(image_forward_action([], image))
        self.assertIsNone(image_forward_action(rows + [('战斗', .4, .75, .8)], image))
        self.assertIsNone(image_forward_action(rows + [('点击任意位置继续', .4, .5, .92)], image))
        from PIL import ImageEnhance
        self.assertIsNone(image_forward_action(rows, ImageEnhance.Brightness(image).enhance(.3)))

    def test_happy_collect_ignores_reward_title(self):
        title = ('点金之触', .70, .5, .46)
        subtitle = ('下一个宝藏的价值提升', .70, .5, .52)
        collect = ('开心收下', .65, .5, .92)
        self.assertEqual(decide([title, collect])[:2], ('开心收下', None))
        self.assertEqual(decide([subtitle, collect])[:2], ('开心收下', None))
        self.assertEqual(decide([collect])[:2], ('开心收下', None))
        self.assertEqual(decide([('圣光护体', .3, .5, .46), collect])[:2], ('开心收下', None))
        self.assertIsNone(decide([title]))
        self.assertIsNone(decide([title, ('开心收下', .65, .1, .92)]))
        self.assertIsNone(decide([title, collect, collect]))

    def test_open_another_group_at_user_request(self):
        button = ('再开一组', .70, .50, .891)
        self.assertEqual(decide([button]), ('再开一组', None, .50, .891))
        self.assertIsNone(decide([('再开一组', .70, .50, .30)]))
        self.assertIsNone(decide([('再开一组', .40, .50, .891)]))
        self.assertIsNone(decide([button, ('开心收下', .70, .50, .92)]))

    def test_floor_seven_rate_from_uploaded_log(self):
        rows = [
            ('小骨头', .7152510732412338, .39111111111111113, .44),
            ('撤离', .6335145433743795, .25833333333333336, .775625),
            ('战斗', .6296811501185099, .7288888888888889, .7740625),
            ('我方胜率', .7413298964500428, .6222222222222222, .8703125),
            ('55% + 8%', .680629187160068, .795, .8678125),
        ]
        self.assertEqual(decide(rows)[:2], ('战斗', 55))
        rows[-1] = ('29% + 8%', .680629187160068, .795, .8678125)
        self.assertEqual(decide(rows)[:2], ('撤离', 29))
        rows[-1] = ('55% + 8%', .64, .795, .8678125)
        self.assertIsNone(decide(rows))
        rows[-1] = ('55% + 8%', .680629187160068, .795, .94)
        self.assertIsNone(decide(rows))

    def test_final_gacha_group_confirm(self):
        button = ('确定', .70, .50, .891)
        self.assertEqual(decide([button]), ('确定', None, .50, .891))
        self.assertIsNone(decide([('确定', .70, .50, .40)]))
        self.assertIsNone(decide([('确定', .70, .10, .891)]))
        self.assertIsNone(decide([('确定', .40, .50, .891)]))
        self.assertIsNone(decide([button, ('再开一组', .70, .50, .92)]))

    def test_pause_waits_for_r_without_restarting(self):
        keys = iter(['p', '', 'x', 'r'])
        with patch('bot.time.sleep'), patch('builtins.print'):
            self.assertTrue(wait_with_controls(0, lambda: next(keys)))
        with patch('builtins.print'):
            self.assertFalse(wait_with_controls(0, lambda: ''))

    def test_unknown_screen_can_wait_for_resume(self):
        keys = iter(['', 'p', 'r'])
        with patch('bot.time.sleep'), patch('builtins.print'):
            wait_for_resume(lambda: next(keys))

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

