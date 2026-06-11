from __future__ import annotations

from post_office.models import BanRule, Message


class BanList:
    def __init__(self, rules: tuple[BanRule, ...]) -> None:
        self.rules = rules

    def matching_rule(self, message: Message) -> BanRule | None:
        for rule in self.rules:
            if rule.matches(message):
                return rule
        return None

    def allows(self, message: Message) -> bool:
        return self.matching_rule(message) is None
