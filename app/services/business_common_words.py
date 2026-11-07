"""Words common to business sections generally, so they say nothing about one issuer.

Derived offline from the business sections of 18 issuers in retained pilot filings: every
word in at least 25% of them. A fixed list, not learned at run time. Development data.
"""
BUSINESS_COMMON_WORDS = frozenset("""
ability about above academic accelerate accelerated access accessible accordance according
accordingly account accountability accounted accounting achieve achieving acquire acquired acquiring
acquisition across action active actively activitie activity actual adapt added addition additional
additionally address addressing adequate adjusted adjustment administration administrative adopt
adopted adoption advance advanced advancement advantage adverse adversely advertising affect
affected affecting affiliate affordable after again against agencie agency agent aggregate agreed
agreement agricultural align allocation allow allowed allowing along already alternative although
aluminum amended amendment america american among amount analysi announced annual annually another
anticipate anticipated applicable application applied apply appointed approach appropriate approval
approved approximately april area arise around arrangement array artificial aspect assess assessment
asset assist assistance associated assume assurance attention attract attracting attractive audit
august authoritie authority authorized availability available average award awarded awareness
background balance bargaining base based basi basic became because become before began begin
beginning behalf being believe below benefit better between beyond billion block board bodie bonuse
branch brand breach breadth bring broad broaden broader build building built bureau business
businesse calendar california canada candidate cannot capabilitie capable capacity capital carbon
career carried case categorie category cause center central certain certificate certification
certified chain challenge change changed changing channel charge charter chemical chief china choice
choose circumstance class client climate close closed closely coaching collaboration collection
collective collectively color combination combine combined commercial commission commitment
committed committee commodity common commonly communication communitie community companie company
comparable compared compensation compete competing competition competitive competitor complete
completed completion complex compliance compliant comply component comprehensive comprise comprised
computing concern concerning condition conduct conducted conducting confidentiality conflict
congress connected connection consequence consider consideration considered consist consistent
consisting consolidated constitute constraint construction consumer consumption contain contained
containing content context continually continue continued continuing continuity continuou
continuously contract contractor contractual contribution control controlling convenience conversion
convert copyright corporate corporation corresponding cost cost-effective could counsel countrie
country course court cover coverage covered covering create creating creation credit criteria
critical culture currency current currently custom customer customized cybersecurity cycle damage
december decision decrease dedicated deemed defined delaware delay deliver delivering delivery
demand demonstrate department depend dependent depending deposit derived described description
design designated designed detailed determine determined develop developed developing development
device differ different difficult digital direct directed directly director disability disclose
disclosure discontinued discovery discussed discussion disease display disruption distribute
distributed distribution distributor district diverse dividend document dollar domestic drive driven
during dynamic e-commerce early earned earning economic economy education educational effect
effective effectively effectiveness efficiencie efficiency efficient effort either electrical
electronic electronically element eligible emerging emission emphasi emphasize employ employed
employee employer employment empower enable enabled enabling enacted encourage ended energy enforce
enforcement engage engaged engagement engineer engineering enhance enhanced enhancing ensure
ensuring enter entered entering enterprise entire entitie entitled entity entry environment
environmental equal equipment equity establish established estimate estimated ethic europe european
evaluate evaluated evaluating evaluation event every evolve evolving examination example exceed
excellence except exception excess exchange exclusive exclusively execute execution executive
exercise exhibit exist existing expand expanded expanding expansion expect expectation expected
expenditure expense experience experienced expertise expiration expire export expose exposure extend
extended extension extensive extent external facilitate facilitie facility factor failure familie
family feature february federal feedback field filed filing finance financial finding finished firm
first fiscal fixed flexibility flexible flow fluctuation focu focuse focused focusing follow
following footprint force foreign form formal formerly forth forward foster found foundation founded
fourth framework fulfill full-time fully function functional functionality fund funding furnish
furnished further furthermore future general generally generate generated generating generation
geographic geographie given giving global globally goal good govern governance government
governmental grade grant granted great greater gross group growing growth guarantee guidance
guideline handling having health healthcare help helping high-performance high-quality higher
highest highly hiring historically history holder holding however http human hundred identification
identified identify identifying immediately impact impacted implement implementation implemented
implementing import important impose imposed improve improved improvement improving incentive
include included including inclusion inclusive income incorporated increase increased increasing
increasingly incur independent independently indicate indirectly individual individually industrial
industrie industry industry-leading influence inform information infrastructure initial initiative
innovate innovation innovative inspection instance institution instrument insurance integrate
integrated integrity intellectual intelligence intend intended interest internal international
internet introduced introduction inventory invest invested investigation investing investment
investor involve issuance issue issued issuer item january jurisdiction knowledge known labor large
largely larger largest later latest launched leader leadership leading learning lease least legal
legislation legislative length lesser level leverage leveraging liabilitie liability license
licensed licensing likely limit limitation limited line liquid listed litigation live local locally
located location logistic long-term longer lower machine maintain maintaining maintenance major
majority make making manage managed management manager managing mandate manner manufacture
manufactured manufacturer manufacturing march mark market marketed marketing marketplace material
materially matter maximize maximum mean meaningful measure media medical meeting member metal method
mexico middle million minimum mission mitigate mobile model modern modification modified money
monitor monitoring month monthly motivate multiple municipal mutual name national natural nature
nearly necessary need needed negative negatively negotiation network non-u north noted notice
november number numerou objective obligation obtain obtained occupational occur occurring october
offer offered offering office officer official offset often on-site ongoing online operate operating
operation operational operator opportunitie opportunity optimize option order organization organize
organized original other otherwise outcome outside outstanding overall oversight overview owned
owner ownership package packaging parameter part participant participate participation particular
particularly partie partner partnership party patent payment pending people percentage perform
performance performed period periodic permanent permit permitted person personal personnel phase
physical pipeline place placement plan planning plant plastic platform point policie policy
political popular portfolio portion position positioned positive possible potential potentially
power practicable practice predict preference preferred premium prepare prescribed presence
president prevent prevention previously price pricing primarily primary principal principally
principle prior prioritie prioritize priority privacy private problem procedure process processe
processing procurement produce produced producer product production productivity professional
profile profit program progress prohibit project promote promotion propertie property propose
proposed proprietary protect protection proven provide provided provider providing provision proxy
public publicly published purchase purchased purpose pursuant pursue pursuing qualified quality
quarter quarterly range ranging rapid rapidly rate rather reach ready reason reasonably receive
received recent recently recognition recognize recognized record recovery recruiting reduce reduced
reducing reduction refer reference referred reflect reflecting regard regarding region regional
register registered registration regular regulate regulated regulating regulation regulator
regulatory relate related relating relation relationship release released relevant reliability
reliable remain remaining report reportable reported reporting represent representation
representative represented representing reputation request require required requirement research
reserve residential resolution resource respect respective respectively respond response
responsibility responsible restrict restriction result resulted resulting retail retain retaining
retention retirement return revenue review reward right risk robust role rule safety sale satisfy
saving scale schedule science scientific scope season seasonal seasonality second secret secretary
section sector secure secured securitie security seek seeking segment select selected selection
selling senior separate september serie serve served service serving several share shareholder sheet
shift shipment shopping short short-term shortage shorter should significant significantly similar
similarly simple since single site size skill skilled small smaller social software solution source
south space special specialized specialty specific specifically specification specified speed
spending stable staff stage standard start state stated statement statu statute statutory steel step
stock stockholder storage store strategic strategie strategy street strength strengthen strive
strong structure subject submit subsequent subsequently subsidiarie subsidiary substance substantial
substantially success successful successfully sufficient suite summary superior supplement supplie
supplied supplier supply support supported supporting survey sustainability sustainable symbol
system table tailored taken taking talent target targeted targeting taxe team technical technologie
technology temporary term termination testing their themselve there therefore thereof these thing
third third-party those three through throughout time timely timing together tolerance tool total
toward track trade trademark trading traditional training transaction transfer transformation
transition transmission transportation treated treatment trend trust type typically ultimately
uncertain uncertainty under understanding union unique unit united university unless until update
updated using usually utilize utilized valuable value variety variou varying vehicle vendor version
vertical virtually visibility vision volume voting warehouse waste water website week well-being
wellness where whether which while whole wholly whose widely within without worker workforce working
workplace world worldwide would written year yield
""".split())
