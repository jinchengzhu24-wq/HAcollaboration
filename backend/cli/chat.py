import sys

from backend.application.services.dialogue_service import DialogueService


def main() -> None:
    _configure_utf8()
    service = DialogueService()

    print("=== 行动研究引导式对话 Demo ===")
    print("输入 quit 可以随时结束。")
    print(service.llm_status_text())
    print()

    initial_idea = input("请先说说你当前的研究想法：").strip()
    if not initial_idea or initial_idea.lower() == "quit":
        return

    project_title = input("如果你想给这个项目起个标题，请输入；没有可直接回车：").strip()
    if project_title.lower() == "quit":
        return
    if not project_title:
        project_title = _default_title(initial_idea)

    session = service.create_session(
        project_title=project_title,
        initial_idea=initial_idea,
    )

    print()
    print(service.build_opening_message(session))
    print()

    plan_confirmation = input("这个分阶段安排合理吗？(y/n)：").strip().lower()
    if plan_confirmation == "quit":
        return
    if plan_confirmation not in {"y", "yes"}:
        adjustment = input("请告诉我你希望怎么调整阶段安排：").strip()
        if adjustment.lower() == "quit":
            return
        print()
        print(service.revise_stage_plan(session, adjustment))
        print()
    else:
        print()
        print(service.confirm_stage_plan(session))
        print()

    while True:
        print(service.get_current_round_label(session))
        print(f"当前剩余轮数（含本轮）：{service.remaining_rounds(session)}")
        print()
        _print_questions(service.get_current_questions(session))

        answers: list[str] = []
        for index, _ in enumerate(session.guiding_questions, start=1):
            answer = input(f"你的回答 {index}：").strip()
            if answer.lower() == "quit":
                print("对话已结束。")
                return
            answers.append(answer)

        latest_input = input("如果你还有额外补充或修订，请继续输入；没有可直接回车：").strip()
        if latest_input.lower() == "quit":
            print("对话已结束。")
            return

        reply = service.advance_session(
            session=session,
            answers=answers,
            latest_input=latest_input or None,
        )

        print()
        print(reply.message)
        print()
        print("一点反馈：")
        print(reply.stage_feedback)
        print()
        print("建议思路：")
        print(reply.guidance)
        print()
        print(reply.draft)
        print()

        if reply.is_complete:
            print("最终总结：")
            print(reply.final_summary or "")
            print()
            print("对话已结束。")
            return

        print(f"接下来还剩 {reply.remaining_rounds} 轮。")
        print()

        should_continue = input("继续下一轮吗？(y/n)：").strip().lower()
        if should_continue not in {"y", "yes"}:
            print("对话已结束。")
            return
        print()


def _print_questions(questions: list[str]) -> None:
    for index, question in enumerate(questions, start=1):
        print(f"{index}. {question}")
    print()


def _default_title(initial_idea: str) -> str:
    shortened = initial_idea.strip().replace("\n", " ")
    if len(shortened) <= 18:
        return shortened
    return f"{shortened[:18]}..."


def _configure_utf8() -> None:
    for stream_name in ("stdin", "stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


if __name__ == "__main__":
    main()
