from app.domain.models.session import FocusArea


def build_focus_prompt(focus_area: FocusArea) -> str:
    return (
        "You are an action-research facilitator. "
        f"Help the teacher advance the section: {focus_area.value}."
    )

