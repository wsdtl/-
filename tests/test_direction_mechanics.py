"""正式战斗方向的机制独立性守卫。"""

from __future__ import annotations

import unittest

from tools.audit_direction_mechanics import audit


class DirectionMechanicsAuditTest(unittest.TestCase):
    def test_all_directions_have_distinct_mechanic_trees(self) -> None:
        report = audit()
        self.assertEqual(report["结论"], "通过", "；".join(report["问题"]))
        self.assertEqual(
            report["摘要"],
            {
                "方向数量": 264,
                "去名后独立能力树": 264,
                "重复组数量": 0,
            },
        )


if __name__ == "__main__":
    unittest.main()
