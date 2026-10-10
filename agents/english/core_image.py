"""Free, deterministic English word core-image explanations.

This module intentionally uses a small reviewed local lexicon. It makes no network
calls and does not guess etymologies for words outside the lexicon.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class WordEntry:
    word: str
    pronunciation: str
    core_image: str
    parts: str
    related: tuple[str, ...]
    example: str
    note: str = ""


_ENTRIES: dict[str, WordEntry] = {
    "inspect": WordEntry(
        word="inspect",
        pronunciation="インスペクト",
        core_image="中をよく見る → 詳しく調べる・検査する",
        parts="in-（中へ）+ spect（見る：ラテン語 specere 系）",
        related=("spectator（観客）", "spectacle（壮観・見もの）", "respect（語源上は同系の「見る」から発達）"),
        example="The mechanic inspected the car.（整備士は車を詳しく点検した。）",
        note="語形成は歴史的に変化しているため、in- + spect は学習用の目安です。",
    ),
    "respect": WordEntry(
        word="respect",
        pronunciation="リスペクト",
        core_image="相手を振り返って見る → 尊重する・敬意を払う",
        parts="re-（後ろへ／再び）+ spect（見る：ラテン語 specere 系）",
        related=("inspect（詳しく調べる）", "spectator（観客）", "perspective（視点）"),
        example="I respect your opinion.（私はあなたの意見を尊重します。）",
        note="現代英語の意味は単純なパーツの足し算だけでは説明できません。",
    ),
    "transport": WordEntry(
        word="transport",
        pronunciation="トランスポート",
        core_image="向こう側へ運ぶ → 輸送する・運ぶ",
        parts="trans-（向こうへ／越えて）+ port（運ぶ：ラテン語 portare）",
        related=("portable（持ち運べる）", "import（中へ持ち込む／輸入する）", "export（外へ運び出す／輸出する）"),
        example="The company transports food by train.（その会社は列車で食品を輸送する。）",
    ),
    "portable": WordEntry(
        word="portable",
        pronunciation="ポータブル",
        core_image="持ち運べる → 携帯できる",
        parts="port（運ぶ：ラテン語 portare）+ -able（〜できる）",
        related=("transport（輸送する）", "import（輸入する）", "export（輸出する）"),
        example="This is a portable charger.（これは携帯用充電器です。）",
    ),
    "import": WordEntry(
        word="import",
        pronunciation="インポート",
        core_image="中へ運び込む → 輸入する",
        parts="im-（in- の変化形：中へ）+ port（運ぶ）",
        related=("export（輸出する）", "transport（輸送する）", "portable（持ち運べる）"),
        example="Japan imports coffee.（日本はコーヒーを輸入する。）",
    ),
    "export": WordEntry(
        word="export",
        pronunciation="エクスポート",
        core_image="外へ運び出す → 輸出する",
        parts="ex-（外へ）+ port（運ぶ）",
        related=("import（輸入する）", "transport（輸送する）", "portable（持ち運べる）"),
        example="They export cars to many countries.（彼らは多くの国へ車を輸出する。）",
    ),
    "spectator": WordEntry(
        word="spectator",
        pronunciation="スペクテイター",
        core_image="見る人 → 観客",
        parts="spect（見る）+ -ator（〜する人）",
        related=("inspect（詳しく調べる）", "respect（尊重する）", "spectacle（見もの）"),
        example="The spectators cheered loudly.（観客たちは大きな声援を送った。）",
    ),
    "perspective": WordEntry(
        word="perspective",
        pronunciation="パースペクティブ",
        core_image="物事を見る位置・角度 → 視点・見方",
        parts="per-（通して）+ spect（見る）に由来する語",
        related=("inspect（詳しく調べる）", "spectator（観客）", "respect（尊重する）"),
        example="Try to see it from her perspective.（彼女の視点からそれを見てみて。）",
        note="語源の細部は複雑なので、パーツは記憶の手がかりとして使ってください。",
    ),

    "circumstance": WordEntry(
        word="circumstance",
        pronunciation="サーカムスタンス",
        core_image="人や出来事の周りに立っている事情 → 状況・環境・境遇",
        parts="circum-（周囲に）+ stance（立つことに関係する語形）。ラテン語 circumstantia（周囲に立つこと・付随する事情）に由来。",
        related=("circum-（周囲に）", "circumnavigate（周航する）", "stand（立つ）"),
        example="Under the circumstances, we did our best.（そのような状況の中で、私たちは最善を尽くした。）",
        note="「周囲にある事情」というコアイメージは記憶の手がかりです。現代の意味を語のパーツだけで完全に説明するものではありません。",
    ),
    "environment": WordEntry(
        word="environment",
        pronunciation="エンヴァイロンメント",
        core_image="人や物を取り巻くもの・条件 → 環境",
        parts="environ（取り巻く、周囲）に関係する語形 + -ment（名詞を作る語尾）。フランス語系の語源を持つ語。",
        related=("environmental（環境の）", "surroundings（周囲のもの）", "environs（周辺地域）"),
        example="Children need a safe learning environment.（子どもには安全な学習環境が必要です。）",
        note="「取り巻くもの・条件」が中心イメージです。語源の細かな歴史を単純な分解だけで断定しないでください。",
    ),

    "postpone": WordEntry(
        word="postpone",
        pronunciation="ポストポーン",
        core_image="後ろの時点へ置く → 延期する・先送りする",
        parts="post-（後ろに／後で）+ pone（置く、ラテン語 ponere に由来する語根形）。",
        related=("position（位置・置くことに関連）", "component（構成要素）", "opponent（対戦相手）"),
        example="We postponed the meeting until Friday.（私たちは会議を金曜日まで延期した。）",
        note="「後ろの時点に置く」は意味を覚えるための手がかりです。関連語の歴史的な語形成はそれぞれ異なるため、形だけで同一の語源と断定しないでください。",
    ),
}


_COMMAND_RE = re.compile(
    r"^(?:コアイメージ|語根|語幹|core\s*image|word\s*root)\s*[:：]?\s+([A-Za-z][A-Za-z'-]{0,63})\s*[?？。！!]*$",
    re.IGNORECASE,
)


def extract_core_image_word(message: str) -> str | None:
    """Return a word only for explicit core-image commands."""
    match = _COMMAND_RE.fullmatch(str(message or "").strip())
    return match.group(1).lower() if match else None


def explain_core_image(word: str) -> str:
    """Explain a reviewed word, or explicitly decline to guess."""
    normalized = str(word or "").strip().lower()
    if not re.fullmatch(r"[a-z][a-z'-]{0,63}", normalized):
        return "英単語を1語指定してください。例：コアイメージ inspect"

    entry = _ENTRIES.get(normalized)
    if entry is None:
        return (
            f"「{normalized}」は、現在の無料ローカル辞書に確かな解説がありません。\n"
            "語源や語根を推測で断定しないため、今回は説明を保留します。\n"
            "別の単語を試すか、辞書項目の追加を依頼してください。"
        )

    lines = [
        f"🔎 {entry.word}（{entry.pronunciation}）",
        f"コアイメージ：{entry.core_image}",
        f"語のパーツ：{entry.parts}",
        "関連語： " + " / ".join(entry.related),
        f"例文：{entry.example}",
    ]
    if entry.note:
        lines.append(f"補足：{entry.note}")
    lines.append("※無料のローカル解説です。外部APIへの問い合わせは行いません。")
    return "\n".join(lines)


def handle_core_image_command(message: str) -> str | None:
    """Return a response for an explicit command, or None if not a match."""
    word = extract_core_image_word(message)
    return explain_core_image(word) if word else None
