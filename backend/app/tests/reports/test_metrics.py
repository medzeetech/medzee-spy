"""Unit tests for :mod:`app.modules.reports.metrics` (F3 T19).

All functions in the module are pure — no async, no I/O — so the tests
build ``ExtractedPayload`` instances inline (for cases that need known
timestamps) or via the ``sample_extracted_payload`` factory (for
shape-only assertions).

See F3 design.md §7 for the metric definitions exercised here.
"""
from __future__ import annotations

import random
from datetime import datetime
from zoneinfo import ZoneInfo

from app.modules.reports.metrics import (
    compute_conversation_count,
    compute_funnel,
    compute_heatmap,
    compute_message_count,
    compute_response_time_distribution,
    compute_score,
)
from app.modules.reports.schemas import (
    ConversationPayload,
    ExtractedPayload,
    FunnelStage,
    MessagePayload,
    ResponseTimeBucket,
)

TZ_SP = ZoneInfo("America/Sao_Paulo")


# ─── Helpers ─────────────────────────────────────────────────────────


def _msg(*, ts: int, from_me: bool, text: str = "x") -> MessagePayload:
    return MessagePayload(ts=ts, from_me=from_me, type="text", text=text)


def _conv(
    *,
    messages: list[MessagePayload],
    is_group: bool = False,
    wa_chatid: str = "5511900000000@s.whatsapp.net",
    contact_name: str = "Paciente",
) -> ConversationPayload:
    return ConversationPayload(
        wa_chatid=wa_chatid,
        contact_name=contact_name,
        is_group=is_group,
        last_message_at=messages[-1].ts if messages else None,
        messages=messages,
    )


def _payload(conversations: list[ConversationPayload]) -> ExtractedPayload:
    return ExtractedPayload(
        message_count=sum(len(c.messages) for c in conversations),
        conversation_count=len(conversations),
        conversations=conversations,
        partial=False,
    )


# ─── compute_message_count / compute_conversation_count ──────────────


def test_message_count_basic(sample_extracted_payload) -> None:
    """5 conversations × 3 messages each → message_count == 15."""
    payload = sample_extracted_payload(message_count=15, conversation_count=5)
    assert compute_message_count(payload) == 15


def test_conversation_count_excludes_groups(sample_extracted_payload) -> None:
    """Group chats are filtered out before the count.

    The factory flags every third conversation as a group when
    ``with_groups=True``. For ``conversation_count=10`` that is indices
    0, 3, 6, 9 — i.e. 4 groups → 6 non-group conversations.
    """
    payload = sample_extracted_payload(
        message_count=60, conversation_count=10, with_groups=True
    )
    n_groups = sum(1 for c in payload.conversations if c.is_group)
    assert n_groups > 0  # sanity: factory actually flagged some
    assert compute_conversation_count(payload) == 10 - n_groups


# ─── compute_response_time_distribution ──────────────────────────────


def test_response_time_distribution_classic() -> None:
    """Hand-built payload exercising 4 of the 6 buckets explicitly.

    Bucket order: [< 5min, 5–30min, 30min–1h, 1h–4h, 4h–24h, > 24h].
    Conv A → bucket 0 (60s), Conv B → bucket 1 (600s),
    Conv C → bucket 3 (7200s),  Conv D → bucket 5 (100_000s).
    """
    convs = [
        _conv(
            wa_chatid="conv-a@s.whatsapp.net",
            messages=[_msg(ts=0, from_me=False), _msg(ts=60, from_me=True)],
        ),
        _conv(
            wa_chatid="conv-b@s.whatsapp.net",
            messages=[_msg(ts=0, from_me=False), _msg(ts=600, from_me=True)],
        ),
        _conv(
            wa_chatid="conv-c@s.whatsapp.net",
            messages=[_msg(ts=0, from_me=False), _msg(ts=7200, from_me=True)],
        ),
        _conv(
            wa_chatid="conv-d@s.whatsapp.net",
            messages=[_msg(ts=0, from_me=False), _msg(ts=100_000, from_me=True)],
        ),
    ]
    dist = compute_response_time_distribution(_payload(convs))

    assert [b.count for b in dist] == [1, 1, 0, 1, 0, 1]
    # The schema guarantees a color is present on every bucket; assert there
    # are 6 non-empty hex strings.
    colors = [b.color for b in dist]
    assert len(colors) == 6
    assert all(c.startswith("#") and len(c) == 7 for c in colors)


def test_response_time_only_leads_no_responses() -> None:
    """A conversation with only inbound leads contributes nothing."""
    convs = [
        _conv(
            messages=[
                _msg(ts=0, from_me=False),
                _msg(ts=60, from_me=False),
                _msg(ts=120, from_me=False),
            ]
        ),
    ]
    dist = compute_response_time_distribution(_payload(convs))
    assert [b.count for b in dist] == [0, 0, 0, 0, 0, 0]


# ─── compute_heatmap ─────────────────────────────────────────────────


def test_heatmap_period_grouping() -> None:
    """One Monday-10h msg and one Tuesday-22h msg map to distinct cells.

    Period order: Madrug., Manhã, Tarde, Noite. Weekday order: Mon..Sun.
    """
    # 2024-01-08 is a Monday — chosen for unambiguous bucket landing.
    monday_10 = datetime(2024, 1, 8, 10, 0, tzinfo=TZ_SP)
    tuesday_22 = datetime(2024, 1, 9, 22, 0, tzinfo=TZ_SP)

    convs = [
        _conv(
            messages=[
                _msg(ts=int(monday_10.timestamp()), from_me=False),
                _msg(ts=int(tuesday_22.timestamp()), from_me=True),
            ]
        ),
    ]
    periods = compute_heatmap(_payload(convs))

    by_label = {p.label: p for p in periods}
    # Manhã, Monday → > 0
    assert by_label["Manhã"].values[0] > 0
    # Noite, Tuesday → > 0
    assert by_label["Noite"].values[1] > 0

    # Everything else is 0.0.
    for p in periods:
        for wd, v in enumerate(p.values):
            if (p.label == "Manhã" and wd == 0) or (p.label == "Noite" and wd == 1):
                continue
            assert v == 0.0, f"unexpected non-zero at ({p.label}, wd={wd})={v}"


# ─── compute_funnel ──────────────────────────────────────────────────


def test_funnel_5_stages() -> None:
    """Five hand-crafted conversations span every stage cumulatively.

    Expected stage counts: [5, 4, 3, 2, 1] (strictly decreasing).
    """
    convs = [
        # c1 — only a lead message: stage 1 only.
        _conv(
            wa_chatid="c1@s.whatsapp.net",
            messages=[_msg(ts=1, from_me=False, text="oi")],
        ),
        # c2 — lead + 1 clinic reply, no keywords, < 3 msgs: stages 1, 2.
        _conv(
            wa_chatid="c2@s.whatsapp.net",
            messages=[
                _msg(ts=1, from_me=False, text="oi"),
                _msg(ts=2, from_me=True, text="ola"),
            ],
        ),
        # c3 — 3 msgs, neutral clinic text: stages 1, 2, 3.
        _conv(
            wa_chatid="c3@s.whatsapp.net",
            messages=[
                _msg(ts=1, from_me=False, text="oi"),
                _msg(ts=2, from_me=True, text="ola"),
                _msg(ts=3, from_me=False, text="ok"),
            ],
        ),
        # c4 — 3 msgs, clinic price keyword "R$ 500": stages 1, 2, 3, 4.
        _conv(
            wa_chatid="c4@s.whatsapp.net",
            messages=[
                _msg(ts=1, from_me=False, text="oi"),
                _msg(ts=2, from_me=True, text="o valor é R$ 500"),
                _msg(ts=3, from_me=False, text="entendi"),
            ],
        ),
        # c5 — clinic msg with BOTH value + booking keywords: stages 1-5.
        _conv(
            wa_chatid="c5@s.whatsapp.net",
            messages=[
                _msg(ts=1, from_me=False, text="oi"),
                _msg(
                    ts=2,
                    from_me=True,
                    text="agendado para amanhã, valor R$ 500",
                ),
                _msg(ts=3, from_me=False, text="ok"),
            ],
        ),
    ]
    funnel = compute_funnel(_payload(convs))

    assert [s.count for s in funnel] == [5, 4, 3, 2, 1]
    # Percentages decreasing too.
    assert [s.pct for s in funnel] == [100.0, 80.0, 60.0, 40.0, 20.0]
    # Stage labels in the documented order.
    assert [s.stage for s in funnel] == [
        "Primeiro contato",
        "Respondidos",
        "Engajados (3+ msgs)",
        "Receberam info / valor",
        "Agendamento confirmado",
    ]


def test_funnel_empty_payload() -> None:
    """Empty payload still returns 5 stages, all zero."""
    payload = ExtractedPayload(
        message_count=0,
        conversation_count=0,
        conversations=[],
        partial=False,
    )
    funnel = compute_funnel(payload)

    assert len(funnel) == 5
    assert all(s.count == 0 for s in funnel)
    assert all(s.pct == 0.0 for s in funnel)


# ─── compute_score ───────────────────────────────────────────────────


def _empty_distribution() -> list[ResponseTimeBucket]:
    return [
        ResponseTimeBucket(faixa="< 5min", count=0, color="#FF6B35"),
        ResponseTimeBucket(faixa="5–30min", count=0, color="#FF6B35"),
        ResponseTimeBucket(faixa="30min–1h", count=0, color="#E8B33C"),
        ResponseTimeBucket(faixa="1h–4h", count=0, color="#E8B33C"),
        ResponseTimeBucket(faixa="4h–24h", count=0, color="#8B3A50"),
        ResponseTimeBucket(faixa="> 24h", count=0, color="#5C1D2E"),
    ]


def _zero_funnel() -> list[FunnelStage]:
    return [
        FunnelStage(stage="Primeiro contato", count=0, pct=0.0),
        FunnelStage(stage="Respondidos", count=0, pct=0.0),
        FunnelStage(stage="Engajados (3+ msgs)", count=0, pct=0.0),
        FunnelStage(stage="Receberam info / valor", count=0, pct=0.0),
        FunnelStage(stage="Agendamento confirmado", count=0, pct=0.0),
    ]


def test_score_low_volume() -> None:
    """Message count below the volume floor → volume_score=0; total caps low."""
    score = compute_score(
        message_count=20,
        response_time_distribution=_empty_distribution(),
        funnel=_zero_funnel(),
    )
    # All four components are zero: response-time (no responses), conversion (0%),
    # response-rate (0%), volume (<50). Total must be 0.
    assert score == 0


def test_score_perfect_clinic() -> None:
    """High volume + all-fast replies + healthy funnel → score >= 80."""
    distribution = [
        ResponseTimeBucket(faixa="< 5min", count=100, color="#FF6B35"),
        ResponseTimeBucket(faixa="5–30min", count=0, color="#FF6B35"),
        ResponseTimeBucket(faixa="30min–1h", count=0, color="#E8B33C"),
        ResponseTimeBucket(faixa="1h–4h", count=0, color="#E8B33C"),
        ResponseTimeBucket(faixa="4h–24h", count=0, color="#8B3A50"),
        ResponseTimeBucket(faixa="> 24h", count=0, color="#5C1D2E"),
    ]
    funnel = [
        FunnelStage(stage="Primeiro contato", count=100, pct=100.0),
        FunnelStage(stage="Respondidos", count=100, pct=100.0),
        FunnelStage(stage="Engajados (3+ msgs)", count=80, pct=80.0),
        FunnelStage(stage="Receberam info / valor", count=50, pct=50.0),
        # Last stage at 25% → conversion_score = min(100, 25*4) = 100.
        FunnelStage(stage="Agendamento confirmado", count=25, pct=25.0),
    ]
    score = compute_score(
        message_count=2000,
        response_time_distribution=distribution,
        funnel=funnel,
    )
    assert score >= 80
    assert score <= 100


def test_score_returns_int_in_range_0_100() -> None:
    """Random plausible inputs always yield 0 ≤ score ≤ 100."""
    rng = random.Random(123)
    for _ in range(50):
        counts = [rng.randint(0, 100) for _ in range(6)]
        distribution = [
            ResponseTimeBucket(
                faixa=faixa,
                count=counts[idx],
                color=color,
            )
            for idx, (faixa, color) in enumerate(
                [
                    ("< 5min", "#FF6B35"),
                    ("5–30min", "#FF6B35"),
                    ("30min–1h", "#E8B33C"),
                    ("1h–4h", "#E8B33C"),
                    ("4h–24h", "#8B3A50"),
                    ("> 24h", "#5C1D2E"),
                ]
            )
        ]
        pct1 = rng.uniform(0, 100)
        pct2 = rng.uniform(0, pct1)
        pct3 = rng.uniform(0, pct2)
        pct4 = rng.uniform(0, pct3)
        pct5 = rng.uniform(0, pct4)
        funnel = [
            FunnelStage(stage="Primeiro contato", count=100, pct=round(pct1, 1)),
            FunnelStage(stage="Respondidos", count=80, pct=round(pct2, 1)),
            FunnelStage(stage="Engajados (3+ msgs)", count=60, pct=round(pct3, 1)),
            FunnelStage(stage="Receberam info / valor", count=40, pct=round(pct4, 1)),
            FunnelStage(stage="Agendamento confirmado", count=20, pct=round(pct5, 1)),
        ]
        msg_count = rng.randint(0, 5000)
        score = compute_score(
            message_count=msg_count,
            response_time_distribution=distribution,
            funnel=funnel,
        )
        assert isinstance(score, int)
        assert 0 <= score <= 100
