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

    "benefit": WordEntry(
        word="benefit",
        pronunciation="ベネフィット",
        core_image="よい結果や助けがもたらされる → 利益・恩恵／利益を得る",
        parts="語源の細かな分解は省略。beneficial / beneficiary などの関連語と一緒に覚える。",
        related=("beneficial（有益な）", "beneficiary（受益者）", "benevolent（善意のある）"),
        example="Regular exercise benefits your health.（定期的な運動は健康に役立つ。）",
        note="語根の説明は記憶用の目安で、現代語の意味を単純な足し算で決めないでください。",
    ),
    "support": WordEntry(
        word="support",
        pronunciation="サポート",
        core_image="下から支える → 支援する・支持する／支え",
        parts="ラテン語 supportare（下から運ぶ・支える）に由来。sub-（下から）と portare（運ぶ）に関係する。",
        related=("supporter（支援者）", "supportive（支援する）", "portable（持ち運べる）"),
        example="My family supports my decision.（家族は私の決断を支持してくれる。）",
    ),
    "transfer": WordEntry(
        word="transfer",
        pronunciation="トランスファー",
        core_image="こちらから向こうへ運ぶ → 移す・転送する／移動",
        parts="trans-（越えて、向こうへ）+ fer（運ぶ：ラテン語 ferre 系）",
        related=("transferred（移された）", "transferrable（移転可能な）", "transport（輸送する）"),
        example="Please transfer the file to this folder.（そのファイルをこのフォルダーに移してください。）",
        note="綴りや品詞によって語形が変わる場合があります。",
    ),
    "transform": WordEntry(
        word="transform",
        pronunciation="トランスフォーム",
        core_image="形を越えて変える → 変形させる・一変させる",
        parts="trans-（別の状態へ、越えて）+ form（形）",
        related=("transformation（変化・変形）", "transformer（変換器）", "form（形）"),
        example="The new road transformed the town.（新しい道路が町を大きく変えた。）",
    ),
    "prevent": WordEntry(
        word="prevent",
        pronunciation="プリベント",
        core_image="先回りして起こらないようにする → 防ぐ・予防する",
        parts="pre-（前もって）+ vent（来る：ラテン語 venire 系）に由来する。",
        related=("prevention（予防）", "preventable（防止できる）", "precaution（予防措置）"),
        example="Washing your hands can help prevent illness.（手洗いは病気の予防に役立つ。）",
        note="語源上の関連語は、現在の意味が同じということではありません。",
    ),
    "discover": WordEntry(
        word="discover",
        pronunciation="ディスカバー",
        core_image="覆いを取り除いて見つける → 発見する・気づく",
        parts="歴史的には古フランス語 descovrir を経てラテン語 discooperire（覆いを外す）に由来。",
        related=("discovery（発見）", "discoverer（発見者）", "cover（覆う）"),
        example="We discovered a quiet café near the station.（駅の近くで静かなカフェを見つけた。）",
    ),
    "describe": WordEntry(
        word="describe",
        pronunciation="ディスクライブ",
        core_image="言葉で特徴を書き表す → 説明する・描写する",
        parts="ラテン語 describere（書き写す・記述する）に由来し、de- と scribere（書く）に関係する。",
        related=("description（説明・描写）", "descriptive（描写的な）", "scribe（書記）"),
        example="Can you describe what happened?（何が起きたのか説明してくれますか。）",
    ),
    "construct": WordEntry(
        word="construct",
        pronunciation="コンストラクト",
        core_image="部品を組み合わせて築く → 建設する・構成する",
        parts="con-（一緒に）+ struct（組み立てる：ラテン語 struere 系）",
        related=("construction（建設・構成）", "structure（構造）", "reconstruct（再建する）"),
        example="They plan to construct a bridge here.（彼らはここに橋を建設する計画だ。）",
    ),
    "reduce": WordEntry(
        word="reduce",
        pronunciation="リデュース",
        core_image="元の方向へ導き戻して小さくする → 減らす・縮小する",
        parts="re-（戻す）+ duc（導く：ラテン語 ducere 系）に由来。",
        related=("reduction（削減）", "reduced（減らされた）", "introduce（導き入れる：語源上の関連に注意）"),
        example="We need to reduce food waste.（食品廃棄を減らす必要がある。）",
        note="語源イメージは意味の手がかりであり、個々の用法は文脈で確認してください。",
    ),
    "produce": WordEntry(
        word="produce",
        pronunciation="プロデュース",
        core_image="前へ導き出す → 生み出す・生産する",
        parts="pro-（前へ）+ duc（導く：ラテン語 ducere 系）に由来。",
        related=("product（製品）", "production（生産）", "productive（生産的な）"),
        example="This farm produces fresh vegetables.（この農場は新鮮な野菜を生産している。）",
        note="名詞 produce は「農産物」を表すこともあり、発音も動詞と異なります。",
    ),

    "alleviate": WordEntry(word="alleviate", pronunciation="アリーヴィエイト", core_image="重荷や痛みを軽くする → 緩和する・和らげる", parts="語源の細かな分解は断定せず、意味の核を記憶の手がかりにする。", related=("relieve（和らげる）", "mitigate（軽減する）", "alleviation（緩和）"), example="The new policy may alleviate the housing shortage.（新しい政策は住宅不足を緩和するかもしれない。）"),
    "exacerbate": WordEntry(word="exacerbate", pronunciation="イグザサベイト", core_image="悪い状態をさらに悪くする → 悪化させる", parts="語源の分解は省略。意味の核と目的語の組み合わせで覚える。", related=("worsen（悪化させる）", "aggravate（悪化させる）", "exacerbation（悪化）"), example="Delays could exacerbate the economic crisis.（遅れは経済危機を悪化させかねない。）"),
    "mitigate": WordEntry(word="mitigate", pronunciation="ミティゲイト", core_image="深刻さや影響を小さくする → 軽減する・緩和する", parts="語源の細かな分解は省略し、alleviate / reduce との使い分けを重視する。", related=("mitigation（軽減）", "alleviate（緩和する）", "offset（相殺する）"), example="The measures are designed to mitigate the risks.（その対策はリスクを軽減するために設計されている。）"),
    "substantiate": WordEntry(word="substantiate", pronunciation="サブスタンシエイト", core_image="根拠を示して確かなものにする → 裏付ける・立証する", parts="substance（実質・根拠）と関連づけて覚えられるが、単純な語の足し算とはみなさない。", related=("substantial（かなりの／実質的な）", "evidence（証拠）", "corroborate（裏付ける）"), example="The researcher could not substantiate the claim.（研究者はその主張を裏付けられなかった。）"),
    "scrutinize": WordEntry(word="scrutinize", pronunciation="スクルーティナイズ", core_image="細部まで注意深く調べる → 精査する", parts="語源の断定的な分解は省略。inspect より厳密に吟味する場面で使われやすい。", related=("scrutiny（精査）", "examine（調べる）", "inspect（検査する）"), example="Auditors scrutinized the company's accounts.（監査人は会社の会計を精査した。）"),
    "undermine": WordEntry(word="undermine", pronunciation="アンダーマイン", core_image="土台の下を掘って弱くする → 損なう・弱体化させる", parts="under（下に）+ mine（坑道を掘ることに関係する語）。現在の意味は文脈とともに覚える。", related=("weaken（弱める）", "erode（徐々に損なう）", "undermining（弱体化）"), example="The scandal undermined public confidence.（その不祥事は国民の信頼を損なった。）"),
    "foster": WordEntry(word="foster", pronunciation="フォスター", core_image="成長するよう世話をする → 育む・促進する", parts="現代語の意味を単純な語根分解で説明せず、よく使われる目的語と一緒に覚える。", related=("foster cooperation（協力を育む）", "promote（促進する）", "nurture（育む）"), example="The program aims to foster innovation.（その計画は革新を促進することを目指している。）"),
    "ubiquitous": WordEntry(word="ubiquitous", pronunciation="ユビキタス", core_image="どこにでも存在する → 至る所にある・遍在する", parts="語源の細部は省略。場所を表す「どこにでも」と結びつけて覚える。", related=("ubiquity（遍在）", "widespread（広範囲に広がった）", "pervasive（広く浸透した）"), example="Smartphones are ubiquitous in modern cities.（現代の都市ではスマートフォンが至る所にある。）"),
    "plausible": WordEntry(word="plausible", pronunciation="プローザブル", core_image="もっともらしく聞こえる → 妥当そうな・信じられそうな", parts="真実だと証明済みという意味ではない。plausible explanation は「もっともらしい説明」。", related=("plausibility（もっともらしさ）", "credible（信用できる）", "speculative（推測に基づく）"), example="She offered a plausible explanation for the error.（彼女はその誤りについてもっともらしい説明をした。）"),
    "arbitrary": WordEntry(word="arbitrary", pronunciation="アービトラリー", core_image="明確な基準に縛られず決められた → 恣意的な・任意の", parts="文脈によって「恣意的」と「任意の」の訳し分けが必要。", related=("arbitrarily（恣意的に）", "discretion（裁量）", "random（無作為の）"), example="The boundary appears arbitrary.（その境界線は恣意的に見える。）"),
    "inherent": WordEntry(word="inherent", pronunciation="インヒアレント", core_image="もともと内側に備わっている → 固有の・本質的な", parts="inherent risk は「その活動自体に内在するリスク」。外から偶然加わったものとは区別する。", related=("inherently（本質的に）", "intrinsic（本来備わった）", "inherent risk（固有リスク）"), example="Every investment carries inherent risks.（どの投資にも固有のリスクがある。）"),
    "subsequent": WordEntry(word="subsequent", pronunciation="サブシクエント", core_image="その後に続いて起こる → その後の・後続の", parts="時間の順序を示す語。subsequent to は「〜の後に」。", related=("subsequently（その後）", "preceding（先行する）", "consequent（結果として生じる）"), example="Subsequent studies confirmed the finding.（その後の研究がその発見を裏付けた。）"),
    "preliminary": WordEntry(word="preliminary", pronunciation="プリリミナリー", core_image="本番の前に行う → 予備の・予備的な", parts="preliminary findings は最終結論ではなく、暫定的な初期結果を指すことが多い。", related=("preliminarily（予備的に）", "initial（初期の）", "tentative（暫定的な）"), example="The team released its preliminary findings.（チームは予備的な調査結果を公表した。）"),
    "ambiguous": WordEntry(word="ambiguous", pronunciation="アンビギュアス", core_image="意味が一つに定まらない → 曖昧な・複数に解釈できる", parts="ambiguous statement は解釈が複数あり得る発言。単に情報が少ないこととは限らない。", related=("ambiguity（曖昧さ）", "unambiguous（曖昧でない）", "equivocal（どちらとも取れる）"), example="The contract contains an ambiguous clause.（その契約には曖昧な条項がある。）"),
    "compel": WordEntry(word="compel", pronunciation="コンペル", core_image="強い力で行動させる → 強制する・余儀なくさせる", parts="compel someone to do は「人に〜することを余儀なくさせる」。", related=("compulsion（強制・衝動）", "compulsory（義務的な）", "force（強制する）"), example="The evidence compelled him to reconsider his view.（その証拠により、彼は自分の見解を再考せざるを得なかった。）"),
    "relinquish": WordEntry(word="relinquish", pronunciation="リリンクウィッシュ", core_image="握っていたものを手放す → 放棄する・譲り渡す", parts="権利・支配・所有物などを手放す、やや改まった語。", related=("relinquishment（放棄）", "surrender（明け渡す）", "yield（譲る）"), example="She refused to relinquish control of the project.（彼女はプロジェクトの主導権を手放すことを拒んだ。）"),
    "stringent": WordEntry(word="stringent", pronunciation="ストリンジェント", core_image="強く締めつけるように厳しい → 厳格な・厳しい", parts="stringent requirements / regulations のように、要件や規制とよく結びつく。", related=("stringency（厳格さ）", "strict（厳しい）", "rigorous（厳密な）"), example="The industry faces stringent safety standards.（その業界は厳格な安全基準に直面している。）"),
    "detrimental": WordEntry(word="detrimental", pronunciation="デトリメンタル", core_image="損害をもたらす → 有害な・悪影響を与える", parts="detrimental to は「〜に有害な／悪影響を与える」。", related=("detriment（損害）", "harmful（有害な）", "adverse（不利な・有害な）"), example="Lack of sleep is detrimental to concentration.（睡眠不足は集中力に悪影響を与える。）"),
    "feasible": WordEntry(word="feasible", pronunciation="フィージブル", core_image="実際に実行できる → 実現可能な", parts="possible よりも、時間・費用・資源などを踏まえて実行可能かという文脈で使われやすい。", related=("feasibility（実現可能性）", "viable（実行可能で持続できる）", "practical（実用的な）"), example="We need to determine whether the plan is feasible.（その計画が実現可能か判断する必要がある。）"),
    "discrepancy": WordEntry(word="discrepancy", pronunciation="ディスクレパンシー", core_image="二つの情報が一致しない → 食い違い・不一致", parts="discrepancy between A and B は「AとBの食い違い」。数値・記録・説明に使われる。", related=("inconsistency（不一致）", "discrepant（食い違った）", "gap（隔たり）"), example="We found a discrepancy between the two reports.（二つの報告書の間に食い違いが見つかった。）"),
    "coherent": WordEntry(word="coherent", pronunciation="コヒアレント", core_image="要素同士がつながってまとまっている → 首尾一貫した・筋の通った", parts="coherent argument は、個々の主張がつながり論理的にまとまった議論。", related=("coherence（一貫性）", "cohesive（まとまりのある）", "consistent（一貫した）"), example="The report presents a coherent argument.（その報告書は筋の通った議論を示している。）"),
    "consensus": WordEntry(word="consensus", pronunciation="コンセンサス", core_image="意見が一つの方向に集まる → 総意・合意", parts="consensus among / on は「〜の間の／〜についての合意」。全員が完全に同意する場合に限らない。", related=("reach a consensus（合意に達する）", "consent（同意する）", "agreement（合意）"), example="The committee reached a consensus on the proposal.（委員会はその提案について合意に達した。）"),
    "tentative": WordEntry(word="tentative", pronunciation="テンタティブ", core_image="まだ確定していない → 暫定的な・仮の", parts="tentative plan / conclusion は、今後の情報で変更され得る計画／結論。", related=("tentatively（暫定的に）", "preliminary（予備的な）", "provisional（仮の）"), example="We have made a tentative decision.（私たちは暫定的な決定をした。）"),
    "resilient": WordEntry(word="resilient", pronunciation="リジリエント", core_image="押されても戻り立ち直る → 回復力のある・しなやかな", parts="人・組織・経済・素材などが、衝撃や困難の後に回復する性質を表す。", related=("resilience（回復力）", "recover（回復する）", "robust（強健な）"), example="Small businesses must be resilient during downturns.（中小企業は景気後退期にも回復力を備える必要がある。）"),
    "allocate": WordEntry(word="allocate", pronunciation="アロケイト", core_image="用途や人ごとに割り当てる → 配分する・割り当てる", parts="allocate resources / funds / time のように、資源・資金・時間の配分に使う。", related=("allocation（配分）", "reallocate（再配分する）", "assign（割り当てる）"), example="The agency allocated funds to rural schools.（その機関は地方の学校に資金を配分した。）"),
    "corroborate": WordEntry(word="corroborate", pronunciation="コロボレイト", core_image="別の証拠で補強する → 裏付ける", parts="語源の細分化は省略。独立した証拠が主張を支える場面で使う。", related=("corroboration（裏付け）", "substantiate（立証する）", "verify（検証する）"), example="The data corroborate her account.（そのデータは彼女の説明を裏付けている。）"),
    "concede": WordEntry(word="concede", pronunciation="コンシード", core_image="抵抗した後で認める → しぶしぶ認める・譲歩する", parts="concede that ... は「…だと認める」。concede a point は議論の一部を認めること。", related=("concession（譲歩）", "admit（認める）", "yield（譲る）"), example="He conceded that the evidence was strong.（彼は証拠が強力であることを認めた。）"),
    "contend": WordEntry(word="contend", pronunciation="コンテンド", core_image="立場を主張して争う → 主張する・論争する", parts="contend that ... は「…と主張する」。compete のように争う意味もある。", related=("contention（主張・論争）", "argue（主張する）", "maintain（主張し続ける）"), example="Some researchers contend that the policy is ineffective.（その政策は効果がないと主張する研究者もいる。）"),
    "assert": WordEntry(word="assert", pronunciation="アサート", core_image="はっきりと前に出して述べる → 断言する・主張する", parts="assert a right は「権利を主張する」。強く述べること自体は正しさの証明ではない。", related=("assertion（断言）", "assertive（自己主張する）", "claim（主張する）"), example="The report asserts that the figures are reliable.（その報告書は数値が信頼できると断言している。）"),
    "refute": WordEntry(word="refute", pronunciation="リフュート", core_image="反証で主張を退ける → 反論する・論破する", parts="単に反対意見を述べるより、根拠を示して誤りを論じる語。", related=("refutation（反証）", "disprove（反証する）", "rebut（反論する）"), example="The new evidence refuted the original theory.（新しい証拠は元の理論を反証した。）"),
    "reconcile": WordEntry(word="reconcile", pronunciation="レコンシル", core_image="対立するものを折り合わせる → 和解させる・調和させる", parts="reconcile A with B は「AとBを両立させる」。数字や記録の照合にも使う。", related=("reconciliation（和解・調整）", "compatible（両立できる）", "resolve（解決する）"), example="It is difficult to reconcile the two accounts.（その二つの説明を両立させるのは難しい。）"),
    "infer": WordEntry(word="infer", pronunciation="インファー", core_image="手がかりから結論を引き出す → 推論する", parts="infer は聞き手・読み手が推論する側。imply は話し手・事実が暗に示す側。", related=("inference（推論）", "deduce（演繹する）", "imply（暗に示す）"), example="We can infer the cause from these results.（これらの結果から原因を推論できる。）"),
    "deduce": WordEntry(word="deduce", pronunciation="ディデュース", core_image="既知の事実から筋道立てて導く → 演繹する・推論する", parts="deduce A from B は「BからAを導く」。infer と重なるが、論理的な導出を強調しやすい。", related=("deduction（推論・控除）", "infer（推論する）", "derive（導き出す）"), example="The detective deduced his location from the clues.（探偵は手がかりから彼の居場所を推理した。）"),
    "implication": WordEntry(word="implication", pronunciation="インプリケーション", core_image="直接言わずに含ませるもの → 含意・影響", parts="implications for は「〜に対する影響・含意」。文脈で論理的含意か実際の影響かを判断する。", related=("imply（暗に示す）", "consequence（結果）", "ramification（波及的影響）"), example="The findings have serious implications for public health.（その調査結果は公衆衛生に重大な影響を持つ。）"),
    "contention": WordEntry(word="contention", pronunciation="コンテンション", core_image="争点として押し出された考え → 主張・論争", parts="a point of contention は「争点」。the contention that ... は「…という主張」。", related=("contend（主張する）", "dispute（論争）", "assertion（主張）"), example="Cost remains a major point of contention.（費用は依然として大きな争点だ。）"),
    "premise": WordEntry(word="premise", pronunciation="プレミス", core_image="議論の出発点として置く前提 → 前提・根拠", parts="on the premise that ... は「…という前提で」。前提が誤っていれば結論も揺らぐ。", related=("premise（前提とする）", "assumption（仮定）", "presuppose（前提とする）"), example="The argument rests on a questionable premise.（その議論は疑わしい前提に基づいている。）"),
    "conjecture": WordEntry(word="conjecture", pronunciation="コンジェクチャー", core_image="証拠が十分でない段階で推し量る → 推測・憶測", parts="学術文脈では証明前の仮説的な推測を指すことがある。", related=("conjecture（推測する）", "speculate（推測する）", "hypothesis（仮説）"), example="At this stage, any explanation would be conjecture.（この段階では、どの説明も推測にすぎない。）"),
    "scrupulous": WordEntry(word="scrupulous", pronunciation="スクルーピュラス", core_image="細部まで良心的に気を配る → 綿密な・良心的な", parts="scrupulous about は「〜に細心の注意を払う」。", related=("scrupulously（細心の注意を払って）", "meticulous（細部まで注意深い）", "conscientious（良心的な）"), example="The editor was scrupulous about accuracy.（編集者は正確さに細心の注意を払った。）"),
    "pervasive": WordEntry(word="pervasive", pronunciation="パーベイシブ", core_image="広い範囲にしみ渡る → 広く浸透した・蔓延する", parts="pervasive influence / problem のように、影響や問題が広範囲に及ぶときに使う。", related=("pervade（浸透する）", "ubiquitous（至る所にある）", "widespread（広範囲の）"), example="Distrust has become pervasive throughout the organization.（不信感が組織全体に広がっている。）"),
    "obsolete": WordEntry(word="obsolete", pronunciation="オブソリート", core_image="使われる時代を過ぎた → 廃れた・時代遅れの", parts="obsolete technology は「旧式化した技術」。単に古いだけでなく、使われなくなった含みがある。", related=("obsolescence（陳腐化）", "outdated（時代遅れの）", "supersede（取って代わる）"), example="The new system made the old equipment obsolete.（新しいシステムによって旧設備は時代遅れになった。）"),
    "intricate": WordEntry(word="intricate", pronunciation="イントリケイト", core_image="細部が複雑に絡み合う → 入り組んだ・複雑な", parts="intricate pattern / network のように、多くの細部が絡む対象に使う。", related=("intricacy（複雑さ）", "complex（複雑な）", "elaborate（精巧な）"), example="The device has an intricate internal structure.（その装置は内部構造が入り組んでいる。）"),
    "indispensable": WordEntry(word="indispensable", pronunciation="インディスペンサブル", core_image="取り除けないほど必要 → 不可欠な", parts="indispensable to / for は「〜に不可欠な」。essential と近い。", related=("indispensability（不可欠性）", "essential（不可欠な）", "vital（極めて重要な）"), example="Trust is indispensable to effective teamwork.（信頼は効果的なチームワークに不可欠だ。）"),
    "profound": WordEntry(word="profound", pronunciation="プロファウンド", core_image="深いところまで及ぶ → 深遠な・重大な", parts="profound effect / change は「重大な影響／大きな変化」。単に強いというより深さを含む。", related=("profoundly（深く・大いに）", "depth（深さ）", "significant（重要な）"), example="The discovery had a profound effect on medicine.（その発見は医学に重大な影響を与えた。）"),
    "ambivalent": WordEntry(word="ambivalent", pronunciation="アンビバレント", core_image="相反する感情を同時に抱く → 相反する気持ちのある", parts="ambivalent about は「〜について複雑な／相反する気持ちを持つ」。ambiguous（意味が曖昧）と区別する。", related=("ambivalence（相反する感情）", "mixed feelings（複雑な気持ち）", "conflicted（葛藤した）"), example="She remains ambivalent about the proposal.（彼女はその提案についてまだ気持ちが揺れている。）"),
    "conspicuous": WordEntry(word="conspicuous", pronunciation="コンスピキュアス", core_image="目立って視界に入る → 目立つ・顕著な", parts="conspicuous by its absence は「ないことがかえって目立つ」。", related=("conspicuously（目立って）", "noticeable（目立つ）", "prominent（際立った）"), example="There was a conspicuous lack of reliable data.（信頼できるデータが明らかに不足していた。）"),
    "diligent": WordEntry(word="diligent", pronunciation="ディリジェント", core_image="手を抜かず粘り強く取り組む → 勤勉な・熱心な", parts="diligent effort / research のように、継続的に注意を払う姿勢を表す。", related=("diligence（勤勉さ）", "diligently（熱心に）", "assiduous（勤勉な）"), example="The team conducted a diligent review of the evidence.（チームは証拠を念入りに検討した。）"),
    "meticulous": WordEntry(word="meticulous", pronunciation="メティキュラス", core_image="細部を一つずつ確認する → 細心の・非常に几帳面な", parts="meticulous attention to detail は「細部への細心の注意」。", related=("meticulously（細心の注意を払って）", "meticulousness（几帳面さ）", "scrupulous（綿密な）"), example="She kept meticulous records of every experiment.（彼女は実験の記録を一つ残らず細かくつけた。）"),
    "plight": WordEntry(word="plight", pronunciation="プライト", core_image="困難に陥った状態 → 苦境・窮状", parts="the plight of ... は「〜の窮状」。深刻な困難にある人々について使われやすい。", related=("in dire straits（窮地にある）", "predicament（困った状況）", "hardship（苦難）"), example="The report highlighted the plight of displaced families.（その報告書は避難を余儀なくされた家族の窮状を取り上げた。）"),
    "incentive": WordEntry(word="incentive", pronunciation="インセンティブ", core_image="行動を起こすきっかけとして与えるもの → 動機・奨励策", parts="financial incentive は「金銭的な誘因」。incentive to do は「〜する動機」。", related=("incentivize（動機づける）", "motivation（動機）", "inducement（誘因）"), example="Tax incentives encouraged firms to invest.（税制上の優遇策が企業の投資を促した。）"),
    "disparity": WordEntry(word="disparity", pronunciation="ディスパリティ", core_image="並べると釣り合わない差 → 格差・不均衡", parts="disparity between A and B は「AとBの格差」。単なる違いより不均衡の含みがある。", related=("disparate（大きく異なる）", "inequality（不平等）", "gap（格差）"), example="The study examined the disparity in access to education.（その研究は教育機会の格差を調べた。）"),
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
