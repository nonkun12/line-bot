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

    "achieve": WordEntry("achieve", "アチーヴ", "目標に手を届かせる → 達成する", "現代英語の意味をイメージ化した説明（語源分解ではありません）", ("achievement（達成）", "accomplish（成し遂げる）", "goal（目標）"), "She achieved her goal.（彼女は目標を達成した。）"),
    "accept": WordEntry("accept", "アクセプト", "差し出されたものを受け取る → 受け入れる・承諾する", "現代英語の意味をイメージ化した説明（語源分解ではありません）", ("acceptance（受け入れ）", "receive（受け取る）", "reject（拒否する）"), "He accepted the offer.（彼はその申し出を受け入れた。）"),
    "affect": WordEntry("affect", "アフェクト", "何かに作用して変化を与える → 影響する", "現代英語の意味をイメージ化した説明。effect（結果・影響）との使い分けに注意。", ("effect（結果・影響）", "influence（影響する）", "impact（影響）"), "Weather can affect your plans.（天気は予定に影響することがある。）"),
    "appear": WordEntry("appear", "アピア", "視界や意識に現れる → 現れる・〜のように見える", "現代英語の意味をイメージ化した説明（語源分解ではありません）", ("appearance（外見・出現）", "disappear（消える）", "seem（〜のように見える）"), "A message appeared on the screen.（画面にメッセージが現れた。）"),
    "apply": WordEntry("apply", "アプライ", "目的に向けて当てはめる → 適用する・申し込む", "用法により「適用する」「応募する」「塗る」などに分かれます。", ("application（申請・応用）", "applicant（応募者）", "apply for（〜に申し込む）"), "I applied for the job.（私はその仕事に応募した。）"),
    "approach": WordEntry("approach", "アプローチ", "対象との距離を縮める → 近づく・取り組み方", "現代英語の意味をイメージ化した説明（語源分解ではありません）", ("approach（近づく／方法）", "near（近い）", "method（方法）"), "We need a new approach.（私たちには新しい取り組み方が必要だ。）"),
    "avoid": WordEntry("avoid", "アヴォイド", "ぶつからないように距離を取る → 避ける", "現代英語の意味をイメージ化した説明（語源分解ではありません）", ("avoidance（回避）", "prevent（防ぐ）", "escape（逃れる）"), "Try to avoid mistakes.（間違いを避けるようにしよう。）"),
    "benefit": WordEntry("benefit", "ベネフィット", "自分にとってプラスになるもの → 利益・恩恵／利益を得る", "名詞と動詞の両方で使います。", ("beneficial（有益な）", "advantage（利点）", "profit（利益）"), "Exercise benefits your health.（運動は健康に役立つ。）"),
    "compare": WordEntry("compare", "コンペア", "二つ以上を並べて見る → 比較する", "compare A with B / compare A to B の形で使います。", ("comparison（比較）", "comparable（比較できる）", "contrast（対比する）"), "Let's compare the two options.（2つの選択肢を比較しよう。）"),
    "complete": WordEntry("complete", "コンプリート", "足りない部分がなく全体がそろう → 完了する・完全な", "動詞・形容詞の両方で使います。", ("completion（完了）", "incomplete（不完全な）", "finish（終える）"), "Please complete the form.（フォームに記入を完了してください。）"),
    "consider": WordEntry("consider", "コンシダー", "選択肢を心の中でよく見る → 検討する・考慮する", "現代英語の意味をイメージ化した説明（語源分解ではありません）", ("consideration（考慮）", "considerate（思いやりのある）", "think about（〜を考える）"), "We should consider the cost.（費用を考慮すべきだ。）"),
    "decide": WordEntry("decide", "ディサイド", "選択肢の間に区切りをつける → 決める", "現代英語の意味をイメージ化した説明（語源分解ではありません）", ("decision（決定）", "decisive（決定的な）", "choose（選ぶ）"), "I decided to stay home.（家にいることに決めた。）"),
    "develop": WordEntry("develop", "ディヴェロップ", "段階を経て形や機能が育つ → 発達する・開発する", "現代英語の意味をイメージ化した説明（語源分解ではありません）", ("development（発展）", "developer（開発者）", "improve（改善する）"), "They developed a useful tool.（彼らは便利な道具を開発した。）"),
    "discover": WordEntry("discover", "ディスカヴァー", "覆いの下にあったものが見つかる → 発見する", "現代英語の意味をイメージ化した説明（語源分解ではありません）", ("discovery（発見）", "uncover（明らかにする）", "invent（発明する）"), "She discovered a small cafe.（彼女は小さなカフェを見つけた。）"),
    "explain": WordEntry("explain", "イクスプレイン", "分かりにくいものをほどいて明らかにする → 説明する", "現代英語の意味をイメージ化した説明（語源分解ではありません）", ("explanation（説明）", "clear（明確な）", "describe（描写する）"), "Could you explain the rule?（その規則を説明してくれますか。）"),
    "express": WordEntry("express", "イクスプレス", "内側にある考えを外に出す → 表現する・伝える", "現代英語の意味をイメージ化した説明（語源分解ではありません）", ("expression（表現）", "impress（印象づける）", "communicate（伝える）"), "He expressed his opinion clearly.（彼は自分の意見をはっきり表現した。）"),
    "improve": WordEntry("improve", "インプルーヴ", "今の状態をより良くする → 改善する・上達する", "現代英語の意味をイメージ化した説明（語源分解ではありません）", ("improvement（改善）", "better（より良い）", "enhance（高める）"), "Practice will improve your English.（練習すれば英語が上達する。）"),
    "involve": WordEntry("involve", "インヴォルヴ", "物事の中に含まれ、関わりを持つ → 含む・巻き込む", "文脈により「必要とする」「参加させる」などにもなります。", ("involvement（関与）", "involved（関係している）", "include（含める）"), "The job involves talking to customers.（その仕事には顧客との会話が含まれる。）"),
    "maintain": WordEntry("maintain", "メインテイン", "状態を保ち続ける → 維持する・主張する", "主張する意味もあるため、文脈に注意します。", ("maintenance（維持）", "keep（保つ）", "sustain（持続させる）"), "It's important to maintain a balance.（バランスを保つことが大切だ。）"),
    "manage": WordEntry("manage", "マネージ", "人や物事を扱い、必要な状態に導く → 管理する・何とかやり遂げる", "manage to do は「何とか〜する」という意味です。", ("management（管理）", "manager（管理者）", "handle（扱う）"), "We managed to finish on time.（私たちは何とか時間内に終えた。）"),
    "prevent": WordEntry("prevent", "プリヴェント", "起きる前に立ちはだかる → 防ぐ・妨げる", "prevent A from doing の形に注意します。", ("prevention（予防）", "preventive（予防の）", "avoid（避ける）"), "A helmet can prevent serious injuries.（ヘルメットは重傷を防ぐことがある。）"),
    "provide": WordEntry("provide", "プロヴァイド", "必要なものを前もって用意する → 提供する", "provide A with B / provide B for A の形があります。", ("provider（提供者）", "provision（供給）", "supply（供給する）"), "The school provides lunch.（その学校は昼食を提供する。）"),
    "reduce": WordEntry("reduce", "リデュース", "量や程度を小さくする → 減らす・縮小する", "reduce A by（Aを〜だけ減らす）と reduce A to（Aを〜まで減らす）を区別します。", ("reduction（削減）", "reduced（減少した）", "decrease（減少する）"), "We need to reduce waste.（廃棄物を減らす必要がある。）"),
    "require": WordEntry("require", "リクワイア", "条件として必要とする → 要求する・必要とする", "受け身の be required to do は「〜することを求められている」です。", ("requirement（必要条件）", "required（必須の）", "need（必要とする）"), "This task requires patience.（この作業には忍耐が必要だ。）"),
    "respond": WordEntry("respond", "レスポンド", "働きかけに対して返す → 返答する・反応する", "respond to の形で「〜に応答する」となります。", ("response（返答・反応）", "responsive（反応のよい）", "reply（返事をする）"), "She responded to my email.（彼女は私のメールに返信した。）"),
    "support": WordEntry("support", "サポート", "下から支えて倒れないようにする → 支援する・支持する", "物理的な支えと、意見・人への支援の両方に使います。", ("supporter（支援者）", "supportive（支援する）", "assist（手助けする）"), "My family supports my decision.（家族は私の決断を支持している。）"),
    "understand": WordEntry("understand", "アンダースタンド", "情報を受け取り、意味をつかむ → 理解する", "現代英語の意味をイメージ化した説明（語源分解ではありません）。under + stand という見た目だけで語源を断定しないでください。", ("understanding（理解）", "misunderstand（誤解する）", "comprehend（理解する）"), "I understand the problem now.（今はその問題が理解できる。）"),
    "transform": WordEntry("transform", "トランスフォーム", "形や状態を別のものへ変える → 変形させる・一変させる", "trans- は「越えて／別の状態へ」の手がかりになります。", ("transformation（変化）", "transfer（移す）", "change（変える）"), "The experience transformed her life.（その経験は彼女の人生を一変させた。）"),
    "transfer": WordEntry("transfer", "トランスファー", "ある場所・人から別の場所・人へ移す → 移す・転送する", "trans- は「越えて／別の場所へ」の手がかりになります。", ("transferable（移転可能な）", "transform（変形させる）", "transport（輸送する）"), "Please transfer the file to my laptop.（そのファイルを私のノートPCに転送してください。）"),
    "prepare": WordEntry("prepare", "プリペア", "必要な状態に整える → 準備する", "prepare for（〜に備える）/ prepare A（Aを準備する）を使い分けます。", ("preparation（準備）", "prepared（準備のできた）", "ready（準備ができた）"), "We prepared for the meeting.（私たちは会議の準備をした。）"),
    "responded": WordEntry("responded", "レスポンディド", "respond の過去形・過去分詞 → 返答した・反応した", "respond の活用形です。基本形 respond も参照してください。", ("respond（返答する）", "response（返答）", "reply（返事をする）"), "He responded quickly.（彼はすぐに返答した。）"),

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
