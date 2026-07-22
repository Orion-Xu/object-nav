from __future__ import annotations

import hashlib
from pathlib import Path

from .config import load_yaml
from .models import NavigationMode, ObjectPolicy


class VocabularyError(ValueError):
    pass


class VocabularyManager:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.version = ""
        self._policies: dict[str, ObjectPolicy] = {}
        self._aliases: dict[str, list[str]] = {}
        self.reload()

    def reload(self) -> None:
        raw_bytes = self.path.read_bytes()
        data = load_yaml(self.path)
        declared = str(data.get("version", "")).strip()
        self.version = declared or hashlib.sha256(raw_bytes).hexdigest()[:12]
        objects = data.get("objects")
        if not isinstance(objects, list) or not objects:
            raise VocabularyError("词表 objects 必须是非空列表")
        policies: dict[str, ObjectPolicy] = {}
        aliases: dict[str, list[str]] = {}
        for index, item in enumerate(objects):
            try:
                label = str(item["canonical_label"]).strip()
                alias_values = tuple(str(v).strip() for v in item["aliases_zh"] if str(v).strip())
                prompt = str(item["prompt_en"]).strip()
                mode = NavigationMode(str(item["navigation_mode"]))
                confidence = float(item["min_confidence"])
                depth_ratio = float(item["min_valid_depth_ratio"])
                standoff = item.get("standoff_m")
                standoff = None if standoff is None else float(standoff)
            except (KeyError, TypeError, ValueError) as exc:
                raise VocabularyError(f"词表第 {index + 1} 项无效: {exc}") from exc
            if not label or not prompt or not alias_values:
                raise VocabularyError(f"词表第 {index + 1} 项存在空字段")
            if label in policies:
                raise VocabularyError(f"规范标签重复: {label}")
            if not 0.0 <= confidence <= 1.0 or not 0.0 <= depth_ratio <= 1.0:
                raise VocabularyError(f"阈值必须在 [0,1]: {label}")
            if standoff is not None and standoff <= 0:
                raise VocabularyError(f"停靠距离必须为正数: {label}")
            policy = ObjectPolicy(label, alias_values, prompt, mode, confidence, depth_ratio, standoff)
            policies[label] = policy
            for alias in alias_values:
                aliases.setdefault(alias, []).append(label)
        duplicate_aliases = {alias: values for alias, values in aliases.items() if len(values) > 1}
        if duplicate_aliases:
            raise VocabularyError(f"中文别名歧义: {duplicate_aliases}")
        self._policies = policies
        self._aliases = aliases

    @property
    def policies(self) -> tuple[ObjectPolicy, ...]:
        return tuple(self._policies.values())

    def get(self, label: str) -> ObjectPolicy:
        return self._policies[label]

    def match_aliases(self, text: str) -> list[ObjectPolicy]:
        matches: list[tuple[int, ObjectPolicy]] = []
        for alias, labels in self._aliases.items():
            if alias in text:
                matches.append((len(alias), self._policies[labels[0]]))
        if not matches:
            return []
        longest = max(length for length, _ in matches)
        unique = {policy.canonical_label: policy for length, policy in matches if length == longest}
        return list(unique.values())
