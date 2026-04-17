"""已实现原子技能注册表与执行器（无 LLM）。"""

from pathlib import Path

from uap.skill.atomic_implemented import (
    MODELING_ATOMIC_SKILL_IDS,
    build_modeling_atomic_registry,
)


def test_registry_keys_match_catalog() -> None:
    reg = build_modeling_atomic_registry()
    assert set(reg.keys()) == set(MODELING_ATOMIC_SKILL_IDS)
    for sid, sk in reg.items():
        assert sk.metadata.skill_id == sid
        assert sk._executor is not None


def test_data_load_csv_under_workspace(tmp_path: Path) -> None:
    reg = build_modeling_atomic_registry()
    sk = reg["data_load_csv"]
    p = tmp_path / "sub" / "a.csv"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x,y\n1,2\n3,4\n", encoding="utf-8")
    out = sk.execute(file_path="sub/a.csv", project_workspace=str(tmp_path))
    assert "error" not in out
    obs = out.get("observation") or ""
    assert "a.csv" in obs and "x" in obs and '"1"' in obs


def test_data_load_csv_rejects_escape(tmp_path: Path) -> None:
    reg = build_modeling_atomic_registry()
    sk = reg["data_load_csv"]
    w = tmp_path / "w"
    w.mkdir()
    out = sk.execute(file_path="../../outside", project_workspace=str(w))
    assert "error" in out


def test_preprocess_normalize() -> None:
    reg = build_modeling_atomic_registry()
    sk = reg["preprocess_normalize"]
    data = [[0.0, 10.0], [5.0, 20.0]]
    out = sk.execute(data=data, method="zscore")
    assert "error" not in out
    obs = out.get("observation") or ""
    assert "标准化" in obs


def test_model_monte_carlo_smoke() -> None:
    reg = build_modeling_atomic_registry()
    sk = reg["model_monte_carlo"]
    out = sk.execute(
        model={"initial_state": {"a": 1.0, "b": 0.0}, "n_steps": 5, "step_noise": 0.01},
        num_samples=20,
    )
    assert "error" not in out
    assert "MC" in (out.get("observation") or "")


def test_get_skill_chain_recommendations_filtered() -> None:
    from uap.skill.atomic_skills import get_skill_chain_recommendations

    chains = get_skill_chain_recommendations("modeling")
    assert chains
    for ch in chains:
        for sid in ch:
            assert sid in MODELING_ATOMIC_SKILL_IDS
