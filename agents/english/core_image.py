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

    "include": WordEntry(
        word="include",
        pronunciation="インクルード",
        core_image="内側に入れておく → 含める・含有する",
        parts="in-（中へ）+ clude（閉じる：ラテン語 claudere 系）",
        related=("exclude（除外する）", "conclude（結論づける）", "inclusion（包含）"),
        example="The price includes breakfast.（料金には朝食が含まれています。）",
        note="include と exclude を対比すると覚えやすい語です。",
    ),
    "exclude": WordEntry(
        word="exclude",
        pronunciation="エクスクルード",
        core_image="外へ閉め出す → 除外する・含めない",
        parts="ex-（外へ）+ clude（閉じる：ラテン語 claudere 系）",
        related=("include（含める）", "conclude（結論づける）", "exclusive（限定的な）"),
        example="The fee excludes tax.（その料金に税金は含まれていません。）",
        note="include と対比すると意味をつかみやすくなります。",
    ),
    "connect": WordEntry(
        word="connect",
        pronunciation="コネクト",
        core_image="結び合わせる → つなぐ・関連づける",
        parts="ラテン語 connectere（結び合わせる）に由来し、con-（一緒に）と nectere（結ぶ）に関連する形。",
        related=("connection（つながり）", "disconnect（切り離す）", "connector（接続器）"),
        example="This road connects the two towns.（この道路は2つの町をつないでいる。）",
        note="connect の con- は「一緒に」のイメージとして覚えられます。",
    ),
    "interrupt": WordEntry(
        word="interrupt",
        pronunciation="インタラプト",
        core_image="途中に割り込んで切る → さえぎる・中断する",
        parts="inter-（間に）+ rupt（破る：ラテン語 rumpere 系）",
        related=("disrupt（混乱させる）", "rupture（破裂）", "interruption（中断）"),
        example="Sorry to interrupt, but I have a question.（話をさえぎってすみませんが、質問があります。）",
        note="rupt を含む語には「破る・切る」のイメージが見られます。",
    ),
    "predict": WordEntry(
        word="predict",
        pronunciation="プリディクト",
        core_image="前もって言う → 予測する",
        parts="pre-（前もって）+ dict（言う：ラテン語 dicere 系）",
        related=("dictate（指示する）", "dictionary（辞書）", "contradict（反論する）"),
        example="Experts predict that prices will rise.（専門家は価格が上がると予測している。）",
        note="dict を含む語には「言う・述べる」に関係するものがあります。",
    ),
    "review": WordEntry(
        word="review",
        pronunciation="レビュー",
        core_image="もう一度見る → 見直す・評価する・批評する",
        parts="re-（再び）+ view（見る）",
        related=("preview（事前に見る）", "viewpoint（視点）", "revision（改訂）"),
        example="Please review the report before sending it.（送信前に報告書を見直してください。）",
        note="文脈により「評価する」「批評する」などの意味にもなります。",
    ),

    "visible": WordEntry(
        word="visible",
        pronunciation="ヴィジブル",
        core_image="目に入って見える → 目に見える・明らかな",
        parts="vis（見る：ラテン語 videre 系）+ -ible（〜できる）",
        related=("vision（視覚・展望）", "invisible（見えない）", "visual（視覚の）"),
        example="The stars were visible after sunset.（日没後、星が見えた。）",
        note="vis/vid は「見る」に関係する語根の手がかりです。",
    ),
    "dictate": WordEntry(
        word="dictate",
        pronunciation="ディクテイト",
        core_image="言葉で指示する → 指図する・書き取らせる",
        parts="dict（言う：ラテン語 dicere 系）に関係する語",
        related=("predict（予測する）", "contradict（反論する）", "dictation（書き取り）"),
        example="The rules dictate how the data is stored.（規則がデータの保存方法を定めている。）",
        note="dict を含む語には「言う・述べる」に関係するものがあります。",
    ),
    "contradict": WordEntry(
        word="contradict",
        pronunciation="コントラディクト",
        core_image="反対のことを言う → 否定する・矛盾する",
        parts="contra-（反対に）+ dict（言う：ラテン語 dicere 系）",
        related=("dictate（指示する）", "contradiction（矛盾）", "predict（予測する）"),
        example="The two reports contradict each other.（2つの報告書は互いに矛盾している。）",
        note="「反対に言う」は意味を覚えるための手がかりです。",
    ),
    "attract": WordEntry(
        word="attract",
        pronunciation="アトラクト",
        core_image="自分の方へ引き寄せる → 引きつける・魅了する",
        parts="ラテン語 attrahere（引き寄せる）に由来する語",
        related=("attraction（魅力・引力）", "distract（注意をそらす）", "attractive（魅力的な）"),
        example="Bright colors attract attention.（鮮やかな色は注意を引く。）",
        note="「引き寄せる」は物理的な引力にも、関心を引く意味にもつながります。",
    ),
    "distract": WordEntry(
        word="distract",
        pronunciation="ディストラクト",
        core_image="注意を別方向へ引っ張る → 気を散らす・注意をそらす",
        parts="dis-（離れて／別方向へ）+ tract（引く：ラテン語 trahere 系）",
        related=("attract（引きつける）", "distraction（気の散ること）", "tract（引くことに関係する語根）"),
        example="Noise can distract me while I work.（作業中、騒音で気が散ることがある。）",
        note="attract と並べて覚えると、引きつける／注意をそらすの対比になります。",
    ),

    "abandon": WordEntry(
        word="abandon", pronunciation="アバンダン",
        core_image="支えや管理を手放す → 見捨てる・断念する",
        parts="語源の細かな分解はここでは断定しない。",
        related=("give up（あきらめる）", "desert（見捨てる）", "abandoned（見捨てられた）"),
        example="They abandoned the plan.（彼らはその計画を断念した。）",
    ),

    "acquire": WordEntry(
        word="acquire", pronunciation="アクワイア",
        core_image="時間や努力を通じて自分のものにする → 得る・習得する",
        parts="語源の細かな分解はここでは断定しない。",
        related=("obtain（獲得する）", "gain（得る）", "acquisition（獲得）"),
        example="She acquired new skills.（彼女は新しい技能を身につけた。）",
    ),

    "adapt": WordEntry(
        word="adapt", pronunciation="アダプト",
        core_image="状況に合う形へ変える → 適応する・改変する",
        parts="語源の細かな分解はここでは断定しない。",
        related=("adjust（調整する）", "adaptation（適応）", "adopt（採用する）"),
        example="We adapted to the new rules.（私たちは新しい規則に適応した。）",
    ),

    "adequate": WordEntry(
        word="adequate", pronunciation="アデクウェット",
        core_image="必要な基準を満たしている → 十分な・適切な",
        parts="語源の細かな分解はここでは断定しない。",
        related=("sufficient（十分な）", "enough（足りる）", "inadequate（不十分な）"),
        example="The room is adequate for our needs.（その部屋は私たちの必要を満たしている。）",
    ),

    "advocate": WordEntry(
        word="advocate", pronunciation="アドヴォケイト",
        core_image="ある考えや人の側に立って支える → 提唱する・擁護する",
        parts="名詞・動詞で発音や用法が異なる。語源分解はここでは断定しない。",
        related=("support（支持する）", "defend（擁護する）", "advocacy（擁護・提唱）"),
        example="They advocate equal access to education.（彼らは教育への平等なアクセスを提唱している。）",
    ),

    "allocate": WordEntry(
        word="allocate", pronunciation="アロケイト",
        core_image="限られたものを役割や相手ごとに割り当てる → 配分する",
        parts="語源の細かな分解はここでは断定しない。",
        related=("assign（割り当てる）", "distribute（配分する）", "allocation（配分）"),
        example="The team allocated more time to testing.（チームはテストにより多くの時間を割り当てた。）",
    ),

    "ambiguous": WordEntry(
        word="ambiguous", pronunciation="アンビギュアス",
        core_image="意味の分かれ道が複数ある → 曖昧な・多義的な",
        parts="語源の細かな分解はここでは断定しない。",
        related=("unclear（不明確な）", "vague（曖昧な）", "ambiguity（曖昧さ）"),
        example="The instructions were ambiguous.（指示は曖昧だった。）",
    ),

    "anticipate": WordEntry(
        word="anticipate", pronunciation="アンティシペイト",
        core_image="先に思い描いて備える → 予期する・期待する",
        parts="語源の細かな分解はここでは断定しない。",
        related=("expect（予期する）", "predict（予測する）", "anticipation（予想）"),
        example="We anticipate higher demand.（需要の増加を予想している。）",
    ),

    "apparent": WordEntry(
        word="apparent", pronunciation="アパレント",
        core_image="見たところ明らかに感じられる → 明白な・見かけの",
        parts="文脈により「明白な」と「見かけ上の」の両方になる。",
        related=("obvious（明白な）", "seem（〜のように見える）", "apparently（どうやら）"),
        example="The cause became apparent later.（原因は後になって明らかになった。）",
    ),

    "arbitrary": WordEntry(
        word="arbitrary", pronunciation="アービトラリー",
        core_image="明確な基準ではなく、その場の判断で決める → 恣意的な",
        parts="語源の細かな分解はここでは断定しない。",
        related=("random（無作為の）", "unreasonable（不合理な）", "arbitrarily（恣意的に）"),
        example="The decision seemed arbitrary.（その決定は恣意的に思えた。）",
    ),

    "assess": WordEntry(
        word="assess", pronunciation="アセス",
        core_image="状況や価値を調べて判断する → 評価する・査定する",
        parts="語源の細かな分解はここでは断定しない。",
        related=("evaluate（評価する）", "estimate（見積もる）", "assessment（評価）"),
        example="We assessed the risks carefully.（私たちはリスクを慎重に評価した。）",
    ),

    "attain": WordEntry(
        word="attain", pronunciation="アテイン",
        core_image="努力して目標地点に届く → 達成する・到達する",
        parts="語源の細かな分解はここでは断定しない。",
        related=("achieve（達成する）", "accomplish（成し遂げる）", "attainment（達成）"),
        example="She attained her goal.（彼女は目標を達成した。）",
    ),

    "bias": WordEntry(
        word="bias", pronunciation="バイアス",
        core_image="判断が一方向に傾いている → 偏り・先入観",
        parts="語源の細かな分解はここでは断定しない。",
        related=("prejudice（偏見）", "inclination（傾向）", "biased（偏った）"),
        example="We must check our own bias.（自分自身の偏りを確認しなければならない。）",
    ),

    "cease": WordEntry(
        word="cease", pronunciation="シース",
        core_image="続いていた動きが止まる → やめる・停止する",
        parts="語源の細かな分解はここでは断定しない。",
        related=("stop（止める）", "halt（停止する）", "cessation（停止）"),
        example="The noise finally ceased.（騒音はついに止んだ。）",
    ),

    "coherent": WordEntry(
        word="coherent", pronunciation="コヒアレント",
        core_image="部分同士がつながり筋が通っている → 一貫した・首尾一貫した",
        parts="語源の細かな分解はここでは断定しない。",
        related=("consistent（一貫した）", "logical（論理的な）", "coherence（一貫性）"),
        example="Please give a coherent explanation.（筋の通った説明をしてください。）",
    ),

    "compel": WordEntry(
        word="compel", pronunciation="コンペル",
        core_image="選択の余地が少ないほど強く動かす → 強制する・余儀なくさせる",
        parts="語源の細かな分解はここでは断定しない。",
        related=("force（強制する）", "oblige（義務づける）", "compulsion（強制）"),
        example="The evidence compelled him to reconsider.（証拠によって彼は再考せざるを得なかった。）",
    ),

    "concede": WordEntry(
        word="concede", pronunciation="コンシード",
        core_image="争っていた点を相手側に認めて譲る → 認める・譲歩する",
        parts="語源の細かな分解はここでは断定しない。",
        related=("admit（認める）", "yield（譲る）", "concession（譲歩）"),
        example="He conceded that she was right.（彼は彼女が正しいと認めた。）",
    ),

    "constrain": WordEntry(
        word="constrain", pronunciation="コンストレイン",
        core_image="動ける範囲を狭める → 制約する・抑える",
        parts="語源の細かな分解はここでは断定しない。",
        related=("restrict（制限する）", "limit（限る）", "constraint（制約）"),
        example="A lack of funds constrained the project.（資金不足が計画を制約した。）",
    ),

    "contemplate": WordEntry(
        word="contemplate", pronunciation="コンテンプレイト",
        core_image="一つのことを落ち着いて見つめ続ける → 熟考する・思い巡らす",
        parts="語源の細かな分解はここでは断定しない。",
        related=("consider（検討する）", "ponder（熟考する）", "contemplation（熟考）"),
        example="She contemplated a career change.（彼女は転職をじっくり考えた。）",
    ),

    "convey": WordEntry(
        word="convey", pronunciation="コンヴェイ",
        core_image="考えや情報を相手へ運ぶ → 伝える・伝達する",
        parts="語源の細かな分解はここでは断定しない。",
        related=("communicate（伝える）", "express（表現する）", "conveyance（輸送・伝達）"),
        example="Her tone conveyed concern.（彼女の口調は懸念を伝えていた。）",
    ),

    "crucial": WordEntry(
        word="crucial", pronunciation="クルーシャル",
        core_image="結果を左右する要所にある → 極めて重要な",
        parts="語源の細かな分解はここでは断定しない。",
        related=("essential（不可欠な）", "critical（重大な）", "crucially（極めて重要に）"),
        example="Timing is crucial to success.（タイミングは成功に極めて重要だ。）",
    ),

    "diminish": WordEntry(
        word="diminish", pronunciation="ディミニッシュ",
        core_image="大きさ・強さ・重要さが小さくなる → 減る・弱まる",
        parts="語源の細かな分解はここでは断定しない。",
        related=("reduce（減らす）", "decrease（減少する）", "diminution（減少）"),
        example="The pain gradually diminished.（痛みは徐々に弱まった。）",
    ),

    "elaborate": WordEntry(
        word="elaborate", pronunciation="イラボレイト",
        core_image="細部を加えて詳しく形にする → 詳しく説明する・精巧な",
        parts="動詞と形容詞で用法・発音が異なる。語源分解はここでは断定しない。",
        related=("explain（説明する）", "detailed（詳細な）", "elaboration（詳述）"),
        example="Could you elaborate on that point?（その点を詳しく説明してもらえますか。）",
    ),

    "enhance": WordEntry(
        word="enhance", pronunciation="エンハンス",
        core_image="価値や質をより高い段階へ上げる → 高める・向上させる",
        parts="語源の細かな分解はここでは断定しない。",
        related=("improve（改善する）", "boost（高める）", "enhancement（向上）"),
        example="The update enhances security.（その更新はセキュリティを強化する。）",
    ),

    "explicit": WordEntry(
        word="explicit", pronunciation="エクスプリシット",
        core_image="意味を隠さず、はっきり表に出す → 明示的な・明確な",
        parts="語源の細かな分解はここでは断定しない。",
        related=("clear（明確な）", "direct（直接的な）", "explicitly（明示的に）"),
        example="The contract contains explicit rules.（契約には明示的な規則が含まれている。）",
    ),

    "feasible": WordEntry(
        word="feasible", pronunciation="フィージブル",
        core_image="現実の条件の中で実行できる → 実行可能な",
        parts="語源の細かな分解はここでは断定しない。",
        related=("practical（実用的な）", "possible（可能な）", "feasibility（実現可能性）"),
        example="We need a feasible solution.（実行可能な解決策が必要だ。）",
    ),

    "fluctuate": WordEntry(
        word="fluctuate", pronunciation="フラクチュエイト",
        core_image="一定せず上下に揺れ動く → 変動する",
        parts="語源の細かな分解はここでは断定しない。",
        related=("vary（変化する）", "oscillate（振動する）", "fluctuation（変動）"),
        example="Prices fluctuate throughout the year.（価格は一年を通じて変動する。）",
    ),

    "fundamental": WordEntry(
        word="fundamental", pronunciation="ファンダメンタル",
        core_image="物事を支える土台に当たる → 基本的な・根本的な",
        parts="語源の細かな分解はここでは断定しない。",
        related=("basic（基本の）", "essential（不可欠な）", "fundamentally（根本的に）"),
        example="Trust is fundamental to teamwork.（信頼はチームワークの根本だ。）",
    ),

    "inevitable": WordEntry(
        word="inevitable", pronunciation="イネヴィタブル",
        core_image="避けて別の結果にすることができない → 避けられない",
        parts="語源の細かな分解はここでは断定しない。",
        related=("unavoidable（避けられない）", "certain（確かな）", "inevitably（必然的に）"),
        example="Some changes are inevitable.（避けられない変化もある。）",
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
