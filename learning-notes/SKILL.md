---
name: learning-notes
description: Use this skill when the user asks to summarize a video, tutorial, article, document, or multiple notes into structured Chinese learning notes for Obsidian/Notion, especially when the user asks for 笔记, 总结成知识点, 整理教程, 融合笔记, or 保留快捷键/步骤/避坑点.
---

# Learning Notes

When summarizing videos, tutorials, articles, documents, or user-provided notes, output structured Chinese learning notes suitable for Obsidian/Notion.

## Output Style

- Use Markdown headings, lists, numbered steps, and bold keywords.
- Write in Chinese by default.
- Preserve important English terms with Chinese explanations, such as Modifier（修改器） and Roughness（粗糙度）.
- Do not produce only a short summary unless the user explicitly asks for one.
- Do not write a transcript-style or chatty answer.
- Do not add external links unless the user explicitly asks.

## Structure

For technical tutorials, organize notes in this order when suitable:

1. 基础概念
2. 核心操作
3. 实战流程
4. 常见问题/避坑
5. 总结思维
6. 英语学习

## Detail Level

Keep notes concise but complete.

Include:
- core concepts
- operation steps
- shortcuts
- menu paths
- important parameters
- warnings and common mistakes
- practical learning takeaways

Avoid:
- mechanical copying
- overly long storytelling
- excessive motivational language
- missing key steps

## Multiple Sources

If the user provides multiple notes or sources:
- Use the version the user says they prefer as the main structure.
- Merge useful extra points from the other sources naturally.
- Do not mechanically concatenate notes.
- Remove duplicate content.

## English Learning Section

At the end, add an "英语学习" section with 5-8 relevant words or expressions.

For each item:
- English term
- Chinese meaning
- simple example sentence
- Chinese translation

Examples should fit adult daily life, work, or learning scenarios.
