"""Seed corpus for the ChromaDB knowledge base.

These are *stable / historical* facts — records, milestones and rules that do
not change week to week. Fast-changing information (recent results, transfers,
current standings) is deliberately NOT stored here; that comes from live web
search at generation time.

Each entry: (document_id, sport, category, text)
"""

from __future__ import annotations

SPORTS: list[str] = [
    "Cricket",
    "Football",
    "Tennis",
    "Badminton",
    "Basketball",
    "Hockey",
    "Formula 1",
    "Athletics",
    "Kabaddi",
    "Chess",
]

# fmt: off
SEED_DOCUMENTS: list[tuple[str, str, str, str]] = [
    # ------------------------------- Cricket -------------------------------
    ("cri-001", "Cricket", "record", "Sachin Tendulkar is the only cricketer to score 100 international centuries — 51 in Tests and 49 in ODIs. He is also the leading run-scorer in both Test and ODI cricket."),
    ("cri-002", "Cricket", "record", "Brian Lara holds the record for the highest individual score in a Test innings: 400 not out for West Indies against England in Antigua in 2004."),
    ("cri-003", "Cricket", "record", "Rohit Sharma holds the record for the highest individual score in a One Day International: 264 against Sri Lanka at Eden Gardens in 2014. He is the only player with three ODI double centuries."),
    ("cri-004", "Cricket", "record", "Muttiah Muralitharan of Sri Lanka is the leading wicket-taker in Test cricket with 800 wickets, and also leads ODI wicket-taking with 534."),
    ("cri-005", "Cricket", "milestone", "Anil Kumble took all 10 wickets in an innings against Pakistan in Delhi in 1999, becoming only the second bowler after Jim Laker to achieve the feat in Test cricket."),
    ("cri-006", "Cricket", "history", "India won its first ICC Cricket World Cup in 1983 at Lord's, beating the West Indies in the final. Kapil Dev was the captain."),
    ("cri-007", "Cricket", "history", "Australia has won the most Cricket World Cups, taking the title in 1987, 1999, 2003, 2007, 2015 and 2023."),
    ("cri-008", "Cricket", "milestone", "Yuvraj Singh hit six sixes in a single over off Stuart Broad during the 2007 ICC World Twenty20, and scored the fastest fifty in T20 international history off 12 balls in the same innings."),
    ("cri-009", "Cricket", "record", "Sir Donald Bradman finished his Test career with a batting average of 99.94. He needed only four runs in his final innings to average 100 but was dismissed for a duck."),
    ("cri-010", "Cricket", "history", "MS Dhoni is the only captain to win all three major ICC white-ball trophies: the 2007 T20 World Cup, the 2011 ODI World Cup and the 2013 Champions Trophy."),
    ("cri-011", "Cricket", "history", "The first ever Test match was played between Australia and England at the Melbourne Cricket Ground in March 1877. Australia won by 45 runs."),
    ("cri-012", "Cricket", "rules", "A cricket over consists of six legal deliveries. In Test cricket a minimum of 90 overs is bowled per day, and a team declares an innings closed at its own choosing."),

    # ------------------------------- Football ------------------------------
    ("foo-001", "Football", "record", "Lionel Messi has won a record eight Ballon d'Or awards, more than any other player in the award's history."),
    ("foo-002", "Football", "history", "Brazil has won the most FIFA World Cups with five titles: 1958, 1962, 1970, 1994 and 2002."),
    ("foo-003", "Football", "history", "Argentina won the 2022 FIFA World Cup in Qatar, beating France on penalties after a 3-3 draw in the final. Lionel Messi scored twice and Kylian Mbappé scored a hat-trick."),
    ("foo-004", "Football", "record", "Real Madrid has won the European Cup / UEFA Champions League more times than any other club, a total that stands well clear of second-placed AC Milan."),
    ("foo-005", "Football", "record", "Cristiano Ronaldo is the all-time leading scorer in the UEFA Champions League with 140 goals, and the all-time leading scorer in men's international football."),
    ("foo-006", "Football", "record", "Just Fontaine of France scored 13 goals at the 1958 World Cup — still the record for the most goals by one player at a single World Cup tournament."),
    ("foo-007", "Football", "record", "Miroslav Klose of Germany is the all-time leading scorer in FIFA World Cup history with 16 goals across four tournaments."),
    ("foo-008", "Football", "history", "Arsenal went through the entire 2003-04 Premier League season unbeaten, winning 26 and drawing 12 of their 38 matches. The side is known as 'The Invincibles'."),
    ("foo-009", "Football", "history", "Manchester United won the continental treble in 1999 — the Premier League, the FA Cup and the UEFA Champions League — under Sir Alex Ferguson."),
    ("foo-010", "Football", "history", "Diego Maradona scored both the 'Hand of God' goal and the 'Goal of the Century' in the same match, against England in the 1986 World Cup quarter-final."),
    ("foo-011", "Football", "record", "Alan Shearer is the Premier League's all-time leading goalscorer with 260 goals. The Premier League itself was founded in 1992."),
    ("foo-012", "Football", "rules", "A football match is 90 minutes split into two halves of 45, plus stoppage time. Each team may field 11 players including a goalkeeper, and VAR reviews are limited to goals, penalties, direct red cards and mistaken identity."),

    # -------------------------------- Tennis -------------------------------
    ("ten-001", "Tennis", "record", "Novak Djokovic holds the record for the most men's singles Grand Slam titles with 24, ahead of Rafael Nadal on 22 and Roger Federer on 20."),
    ("ten-002", "Tennis", "record", "Margaret Court holds the record for the most singles Grand Slam titles by any player with 24, though many came before the Open Era began in 1968."),
    ("ten-003", "Tennis", "record", "Serena Williams won 23 singles Grand Slam titles, the most by any player in the Open Era."),
    ("ten-004", "Tennis", "record", "Rafael Nadal has won the French Open a record 14 times, earning the nickname 'The King of Clay'."),
    ("ten-005", "Tennis", "record", "Roger Federer won the Wimbledon men's singles title eight times, more than any other man."),
    ("ten-006", "Tennis", "milestone", "Steffi Graf completed the Golden Slam in 1988, winning all four Grand Slam singles titles plus Olympic gold in the same calendar year — the only player ever to do so."),
    ("ten-007", "Tennis", "rules", "Wimbledon is the only Grand Slam played on grass. The Australian Open and US Open are played on hard courts and the French Open on clay."),
    ("ten-008", "Tennis", "history", "Rod Laver is the only player to win the calendar-year Grand Slam twice, in 1962 as an amateur and in 1969 in the Open Era."),
    ("ten-009", "Tennis", "record", "Martina Navratilova won a record nine Wimbledon women's singles titles and holds the record for most singles titles overall in the Open Era with 167."),
    ("ten-010", "Tennis", "rules", "A tennis set is won by the first player to six games with a margin of two. All four Grand Slams now use a tiebreak in the deciding set, a change completed in 2022."),

    # ------------------------------ Badminton ------------------------------
    ("bad-001", "Badminton", "record", "PV Sindhu won silver at the 2016 Rio Olympics and bronze at Tokyo 2020, making her the first Indian woman to win two individual Olympic medals."),
    ("bad-002", "Badminton", "history", "Saina Nehwal became the first Indian to win an Olympic medal in badminton, taking bronze at the London 2012 Games."),
    ("bad-003", "Badminton", "record", "Lin Dan of China is the only player to win two Olympic singles gold medals in badminton, at Beijing 2008 and London 2012."),
    ("bad-004", "Badminton", "history", "Badminton became a full Olympic medal sport at the Barcelona 1992 Games."),
    ("bad-005", "Badminton", "history", "India won the Thomas Cup — the men's world team championship — for the first time in 2022, beating 14-time champions Indonesia 3-0 in the final."),
    ("bad-006", "Badminton", "rules", "Badminton switched to the 21-point rally scoring system in 2006, replacing the older 15-point service-only scoring. A match is best of three games."),
    ("bad-007", "Badminton", "history", "The All England Open is badminton's oldest tournament, first held in 1899. Prakash Padukone became the first Indian to win it in 1980, and Pullela Gopichand followed in 2001."),
    ("bad-008", "Badminton", "record", "Indonesia has won the Thomas Cup more times than any other nation, and China leads the women's equivalent, the Uber Cup."),
    ("bad-009", "Badminton", "rules", "A badminton court is 13.4 metres long and 6.1 metres wide for doubles, narrowing to 5.18 metres for singles. The net is 1.55 metres high at the posts."),
    ("bad-010", "Badminton", "record", "A badminton shuttlecock can leave the racket faster than the ball in almost any other racket sport; smash speeds beyond 400 km/h have been recorded in testing conditions."),

    # ----------------------------- Basketball ------------------------------
    ("bas-001", "Basketball", "record", "LeBron James passed Kareem Abdul-Jabbar to become the NBA's all-time leading scorer in February 2023, ending a record that had stood for 39 years."),
    ("bas-002", "Basketball", "record", "Wilt Chamberlain scored 100 points in a single NBA game against the New York Knicks in 1962 — still the league record."),
    ("bas-003", "Basketball", "record", "Bill Russell won 11 NBA championships with the Boston Celtics, more than any other player in league history."),
    ("bas-004", "Basketball", "history", "Michael Jordan won six NBA championships with the Chicago Bulls and was named Finals MVP in all six of those series."),
    ("bas-005", "Basketball", "history", "The three-point line was introduced to the NBA for the 1979-80 season."),
    ("bas-006", "Basketball", "record", "Stephen Curry is the NBA's all-time leader in three-pointers made, a record he took from Ray Allen in December 2021."),
    ("bas-007", "Basketball", "history", "The United States men's team, nicknamed the 'Dream Team', won gold at the 1992 Barcelona Olympics — the first Games where NBA professionals were allowed to compete."),
    ("bas-008", "Basketball", "rules", "An NBA game is four quarters of 12 minutes each, while FIBA international games use four quarters of 10 minutes."),
    ("bas-009", "Basketball", "rules", "The NBA shot clock is 24 seconds; FIBA also uses 24 seconds, resetting to 14 after an offensive rebound."),
    ("bas-010", "Basketball", "history", "Basketball was invented by James Naismith in Springfield, Massachusetts in 1891, originally using peach baskets as goals."),

    # -------------------------------- Hockey -------------------------------
    ("hoc-001", "Hockey", "record", "India has won eight Olympic gold medals in men's field hockey, the most of any nation, including six consecutive golds from 1928 to 1956."),
    ("hoc-002", "Hockey", "history", "Dhyan Chand was central to India's Olympic hockey golds in 1928, 1932 and 1936. His birthday, 29 August, is celebrated in India as National Sports Day."),
    ("hoc-003", "Hockey", "history", "India won bronze in men's hockey at the Tokyo 2020 Olympics, ending a 41-year wait for an Olympic hockey medal, and repeated bronze at Paris 2024."),
    ("hoc-004", "Hockey", "rules", "A field hockey match is played in four quarters of 15 minutes each, with 11 players per side including a goalkeeper."),
    ("hoc-005", "Hockey", "history", "The men's Hockey World Cup was first held in 1971. Pakistan has won it four times, more than any other nation."),
    ("hoc-006", "Hockey", "rules", "Only the flat side of a field hockey stick may be used to play the ball; using the rounded side is a foul."),
    ("hoc-007", "Hockey", "rules", "A penalty corner is a primary scoring route in field hockey, and the drag-flick is the most common modern conversion technique."),
    ("hoc-008", "Hockey", "history", "The FIH Pro League, an annual home-and-away international league for men's and women's teams, was launched in 2019."),
    ("hoc-009", "Hockey", "record", "The Netherlands, Australia and Germany are the dominant modern powers in international field hockey alongside India, Belgium and Argentina."),
    ("hoc-010", "Hockey", "rules", "A goal in field hockey counts only if the ball is played by an attacker inside the shooting circle, a 14.63-metre arc in front of goal."),

    # ------------------------------ Formula 1 ------------------------------
    ("f1-001", "Formula 1", "record", "Lewis Hamilton and Michael Schumacher share the record for the most Formula 1 World Drivers' Championships, with seven each."),
    ("f1-002", "Formula 1", "record", "Lewis Hamilton holds the Formula 1 records for the most race wins and the most pole positions."),
    ("f1-003", "Formula 1", "history", "Ferrari is the oldest and most successful constructor in Formula 1 history, leading on both Constructors' Championships and total race wins."),
    ("f1-004", "Formula 1", "record", "Max Verstappen won four consecutive Formula 1 World Drivers' Championships from 2021 to 2024."),
    ("f1-005", "Formula 1", "history", "The Monaco Grand Prix is the slowest and most prestigious race on the Formula 1 calendar, run on public streets around Monte Carlo."),
    ("f1-006", "Formula 1", "history", "The Indian Grand Prix was held at the Buddh International Circuit near Greater Noida for three seasons, from 2011 to 2013."),
    ("f1-007", "Formula 1", "rules", "Formula 1 awards points to the top ten finishers on a 25-18-15-12-10-8-6-4-2-1 scale."),
    ("f1-008", "Formula 1", "history", "Formula 1 introduced ground-effect aerodynamic regulations for the 2022 season, reshaping car design to allow closer racing."),
    ("f1-009", "Formula 1", "history", "Juan Manuel Fangio won five World Championships in the 1950s driving for four different constructors — a versatility record that still stands."),
    ("f1-010", "Formula 1", "record", "Sebastian Vettel became Formula 1's youngest World Champion in 2010, winning the title with Red Bull at the age of 23."),

    # ------------------------------ Athletics ------------------------------
    ("ath-001", "Athletics", "record", "Usain Bolt holds the men's 100 m world record at 9.58 seconds, set in Berlin in 2009, and the 200 m world record at 19.19 seconds from the same championships."),
    ("ath-002", "Athletics", "record", "Florence Griffith-Joyner's women's 100 m world record of 10.49 seconds has stood since 1988."),
    ("ath-003", "Athletics", "history", "Neeraj Chopra won javelin gold at the Tokyo 2020 Olympics — India's first Olympic gold in athletics — and followed it with silver at Paris 2024."),
    ("ath-004", "Athletics", "milestone", "Eliud Kipchoge became the first person to run the marathon distance under two hours, clocking 1:59:40 at the unofficial INEOS 1:59 Challenge in Vienna in 2019."),
    ("ath-005", "Athletics", "rules", "The marathon distance is 42.195 kilometres, standardised at the 1908 London Olympics and formalised in 1921."),
    ("ath-006", "Athletics", "record", "Carl Lewis won nine Olympic gold medals across four Games between 1984 and 1996, including four in a row in the long jump."),
    ("ath-007", "Athletics", "rules", "The decathlon is contested over two days and comprises ten events; the women's equivalent, the heptathlon, has seven."),
    ("ath-008", "Athletics", "record", "Sergey Bubka set 35 world records in the pole vault and was the first man to clear six metres."),
    ("ath-009", "Athletics", "history", "Jesse Owens won four gold medals at the 1936 Berlin Olympics, in the 100 m, 200 m, long jump and 4x100 m relay."),
    ("ath-010", "Athletics", "history", "The sport's world governing body, founded in 1912 as the IAAF, was renamed World Athletics in 2019."),

    # ------------------------------- Kabaddi -------------------------------
    ("kab-001", "Kabaddi", "history", "India won the men's Kabaddi World Cup in 2004, 2007 and 2016, dominating the standard-style international format."),
    ("kab-002", "Kabaddi", "history", "The Pro Kabaddi League, India's franchise competition, launched in 2014 and turned kabaddi into a prime-time television sport."),
    ("kab-003", "Kabaddi", "rules", "A kabaddi raid lasts 30 seconds, during which the raider must continuously chant 'kabaddi' without taking a breath."),
    ("kab-004", "Kabaddi", "record", "Pardeep Narwal is the all-time leading raid-point scorer in the Pro Kabaddi League and is famous for his signature 'Dubki' dive."),
    ("kab-005", "Kabaddi", "rules", "A kabaddi team fields seven players on the mat at a time, from a squad of twelve."),
    ("kab-006", "Kabaddi", "history", "Kabaddi featured as a demonstration sport at the 1936 Berlin Olympics and became a medal sport at the Asian Games in 1990."),
    ("kab-007", "Kabaddi", "history", "India won every Asian Games men's kabaddi gold from 1990 until 2018, when Iran took the title."),
    ("kab-008", "Kabaddi", "rules", "Crossing the bonus line with at least six defenders on the mat earns the raider a bonus point."),
    ("kab-009", "Kabaddi", "rules", "A kabaddi match lasts 40 minutes, split into two halves of 20 minutes with a five-minute break."),
    ("kab-010", "Kabaddi", "rules", "An 'all out' — eliminating the entire opposing side — awards the attacking team two bonus points on top of the tackle points."),

    # -------------------------------- Chess --------------------------------
    ("che-001", "Chess", "history", "D Gukesh became the youngest undisputed World Chess Champion in December 2024, winning the title at 18 by beating Ding Liren in Singapore."),
    ("che-002", "Chess", "history", "Viswanathan Anand was World Chess Champion from 2007 to 2013 and became India's first Grandmaster in 1988."),
    ("che-003", "Chess", "record", "Magnus Carlsen holds the highest classical FIDE rating ever achieved, peaking at 2882 in 2014."),
    ("che-004", "Chess", "history", "Garry Kasparov lost a six-game match to IBM's Deep Blue in 1997, the first time a reigning world champion lost a match to a computer under standard conditions."),
    ("che-005", "Chess", "history", "Bobby Fischer beat Boris Spassky in the 1972 'Match of the Century' in Reykjavik, ending 24 years of Soviet dominance of the world title."),
    ("che-006", "Chess", "history", "India won gold in both the open and women's sections of the 2024 Chess Olympiad in Budapest, its first Olympiad titles."),
    ("che-007", "Chess", "rules", "A chessboard has 64 squares and each side begins with 16 pieces: eight pawns, two rooks, two knights, two bishops, a queen and a king."),
    ("che-008", "Chess", "history", "FIDE, the international chess federation, was founded in Paris in 1924. Its motto is 'Gens una sumus' — we are one people."),
    ("che-009", "Chess", "record", "Judit Polgár is widely regarded as the strongest female player in history; she never competed in the women's world championship cycle, playing in the open category instead."),
    ("che-010", "Chess", "rules", "The Sicilian Defence, beginning 1.e4 c5, is the most popular reply to 1.e4 at elite level."),
]
# fmt: on
