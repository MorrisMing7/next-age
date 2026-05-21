---
name: clean-code
description: "Use it to transform \"code that works\" into \"code that is clean.\", especially when: **Writing new code**: To ensure high quality from the start.**Refactoring legacy code**: To identify and remove code smells.**Reviewing Pull Requests**: To provide constructive, principle-based feedback."
---

<!-- Source: ClawForge (https://github.com/sickn33/antigravity-awesome-skills/blob/main/skills/clean-code/SKILL.md) -->

# Clean Code Skill

This skill embodies the principles of "Clean Code" by Robert C. Martin (Uncle Bob). 

## 🧠 Core Philosophy
> "Code is clean if it can be read, and enhanced by a developer other than its original author." — Grady Booch

## 1. Meaningful Names
- **Use Intention-Revealing Names**: `elapsedTimeInDays` instead of `d`.
- **Avoid Disinformation**: Don't use `accountList` if it's actually a `Map`.
- **Make Meaningful Distinctions**: Avoid `ProductData` vs `ProductInfo`.
- **Use Pronounceable/Searchable Names**: Avoid `genymdhms` ，在中文场景下某些术语英文翻译会过长，可以考虑使用汉语拼音首字母表示.
- **Class Names**: Use nouns (`Customer`, `WikiPage`). Avoid `Manager`, `Data`.
- **Method Names**: Use verbs (`postPayment`, `deletePage`).

## 2. Functions
- **Small!**: Functions should be shorter than you think. Aim for fewer than 30 lines; 100 lines is a practical ceiling for complex logic — beyond that, the function likely does more than one thing.
- **Do One Thing**: A function should do only one thing, and do it well.
- **One Level of Abstraction**: Don't mix high-level business logic with low-level details (like regex).
- **Descriptive Names**: `isPasswordValid` is better than `check`.
- **Arguments**: 0 is ideal, 1-3 is okay, 4+ requires a very strong justification.
- **No Side Effects**: Functions shouldn't secretly change global state.
- **避免太短的函数**: Conversely, don't extract a function just to wrap a trivial 1–3 line expression. Extract only when the logic is non-trivial (involves multiple conditionals or loops) AND it is reused in 3 or more places. Otherwise keep it inline.

## 3. Comments
- **Don't Comment Bad Code—Rewrite It**: Most comments are a sign of failure to express ourselves in code.
- **Explain Yourself in Code**: 
  ```python
  # Check if employee is eligible for full benefits
  if employee.flags & HOURLY and employee.age > 65:
  ```
  vs
  ```python
  if employee.isEligibleForFullBenefits():
  ```
- **Good Comments**: Legal, Informative (regex intent), Clarification (external libraries), TODOs.
- **Bad Comments**: Mumbling, Redundant, Misleading, Mandated, Noise, Position Markers.

## 4. Formatting
- **The Newspaper Metaphor**: High-level concepts at the top, details at the bottom.
- **Vertical Density**: Related lines should be close to each other.
- **Distance**: Variables should be declared near their usage.
- **Indentation**: Essential for structural readability.

## 5. Objects and Data Structures
- **Data Abstraction**: Hide the implementation behind interfaces.
- **The Law of Demeter**: A module should not know about the innards of the objects it manipulates. Avoid `a.getB().getC().doSomething()`.
- **Plain Data Carriers**: Use simple structs, records, or data classes with public fields and no behavior when the sole purpose is to transport data.

## 6. Error Handling
- **Use the Language's Error Mechanism**: Prefer exceptions, Result/Either types, or explicit error returns over sentinel return codes. The error path should not obscure the happy path.
- **Define Error Boundaries First**: Establish how errors propagate and where they are handled before writing the main logic.
- **Avoid Null / Nil Sentinels**: Return an empty collection, an Optional/Maybe type, or a dedicated absence marker rather than null/nil. This eliminates an entire class of runtime errors.
- **Don't Pass Null / Nil**: If a parameter is required, enforce it at the boundary (assertions, non-nullable types) so the rest of the code can assume it's present.

## 7. Unit Tests
- **The Three Laws of TDD**:
  1. Don't write production code until you have a failing unit test.
  2. Don't write more of a unit test than is sufficient to fail.
  3. Don't write more production code than is sufficient to pass the failing test.
- **F.I.R.S.T. Principles**: Fast, Independent, Repeatable, Self-Validating, Timely.

## 8. Classes
- **Small!**: Classes should have a single responsibility (SRP).
- **The Stepdown Rule**: We want the code to read like a top-down narrative.

## 9. Smells and Heuristics
- **Rigidity**: Hard to change.
- **Fragility**: Breaks in many places.
- **Immobility**: Hard to reuse.
- **Viscosity**: Hard to do the right thing.
- **Needless Complexity/Repetition**.

## 🛠️ Implementation Checklist
- [ ] Is this function concise and focused? (See "Small!" and "避免太短的函数" above.)
- [ ] Does this function do exactly one thing?
- [ ] Are all names searchable and intention-revealing?
- [ ] Have I avoided comments by making the code clearer?
- [ ] Am I passing too many arguments?
- [ ] Is there a failing test for this change?

## Limitations
- Do not treat the output as a substitute for environment-specific validation, testing, or expert review.
- Stop and ask for clarification if required inputs, permissions, safety boundaries, or success criteria are missing.