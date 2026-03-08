from app.core.config import settings


def _load_prompt(source_type: str = "akt") -> str:
    if source_type == "tinglysningsattest":
        path = settings.prompts_path / "extract_tinglysningsattest.txt"
        if path.exists():
            return path.read_text(encoding="utf-8")
    if source_type == "enrich_servitut":
        path = settings.prompts_path / "enrich_servitut.txt"
        if path.exists():
            return path.read_text(encoding="utf-8")
    return (settings.prompts_path / "extract_servitut.txt").read_text(encoding="utf-8")
