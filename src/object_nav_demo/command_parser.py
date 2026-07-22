from __future__ import annotations

import re
import time
import uuid
from collections.abc import Collection

from .models import NavigationMode, ParseResult
from .vocabulary_manager import VocabularyManager


class CommandParser:
    ACTION_PATTERN = re.compile(r"^(请|麻烦你|你能|可以)?(帮我)?(寻找|找一下|找一找|找|去找|带我去找|定位)(一下)?")

    def __init__(self, vocabulary: VocabularyManager):
        self.vocabulary = vocabulary

    def parse(self, text: str, supported_labels: Collection[str]) -> ParseResult:
        now = time.time()
        task_id = uuid.uuid4().hex
        cleaned = re.sub(r"[\s，。！？!?、]+", "", text or "")
        if not cleaned:
            return self._reject(task_id, text, now, "指令为空")
        action = self.ACTION_PATTERN.match(cleaned)
        if not action:
            return self._reject(task_id, text, now, "仅支持‘寻找/找/去找/帮我找 + 物体’")
        target_text = cleaned[action.end():]
        matches = self.vocabulary.match_aliases(target_text)
        if not matches:
            return self._reject(task_id, text, now, "目标未配置，请从支持列表选择")
        if len(matches) != 1:
            return self._reject(task_id, text, now, "目标存在歧义")
        policy = matches[0]
        if target_text not in policy.aliases_zh:
            return self._reject(task_id, text, now, "指令含有未识别的目标描述")
        if policy.navigation_mode is NavigationMode.DISABLED:
            return self._reject(task_id, text, now, "该目标已禁用，不启动检测或运动")
        if policy.canonical_label not in set(supported_labels):
            return self._reject(task_id, text, now, "当前检测后端不支持该目标")
        return ParseResult(True, task_id, text, now, self.vocabulary.version, policy)

    def _reject(self, task_id: str, text: str, now: float, reason: str) -> ParseResult:
        return ParseResult(False, task_id, text, now, self.vocabulary.version, reason=reason)
