# FishMarket mini-wiki

Short, plain-text notes on things the NOAA landings and GBIF data cannot tell you: what terms mean, the stock status of
the main species, rules, gear, handling and labeling. Every entry has one source link and the date it was read.
Edit freely; `python -m fishmarket.wiki check` validates the format. Keep entries under 100 words.
Status and rule entries can go stale: always follow the source link for the latest.

## ex_vessel | Ex-vessel value (dockside price)
type: term
keywords: ex-vessel, dockside, first buyer, first shoreside buyer, what fishermen are paid, price at the dock, wholesale vs dockside
retrieved: 2026-10-28
source: https://caseagrant.ucsd.edu/sites/default/files/7Bglossary_4Nov2011.pdf
Ex-vessel value is the value of the catch based on the price paid to fishermen when they deliver it to the first shoreside buyer. It leaves out value added later by processors, wholesalers or retailers, so NOAA dockside prices are not what shoppers or restaurants pay.

## overfishing_overfished | Overfishing vs overfished
type: term
keywords: overfishing, overfished, difference between, stock status, how many stocks, rebuilt, status of stocks
retrieved: 2026-10-28
source: https://www.fisheries.noaa.gov/national/sustainable-fisheries/status-stocks-2024
Overfishing means a stock has a harvest rate higher than the rate that produces its maximum sustainable yield (MSY). Overfished means its population size is too low, which jeopardizes its ability to produce MSY. At the end of 2024 NOAA listed 23 stocks on the overfishing list and 42 on the overfished list, out of 522 stocks or stock complexes under 45 fishery management plans. One stock was rebuilt in 2024, bringing the total to 51 since 2000.

## msy_oy | Maximum sustainable yield and optimum yield
type: term
keywords: msy, maximum sustainable yield, optimum yield, sustainable catch, how much can be caught
retrieved: 2026-10-28
source: https://caseagrant.ucsd.edu/sites/default/files/7Bglossary_4Nov2011.pdf
Maximum sustainable yield (MSY) is the largest long-term average catch that can be taken from a stock under prevailing ecological and environmental conditions. Optimum yield (OY) is the amount of fish that provides the greatest overall benefit to the nation, based on MSY and adjusted for economic, social and ecological factors, including rebuilding overfished stocks.

## catch_shares | Catch shares and individual fishing quotas
type: rules
keywords: catch share, catch shares, individual fishing quota, ifq, quota, tac, total allowable catch, allocation, turf, sector
retrieved: 2026-10-28
source: https://www.fisheries.noaa.gov/national/sustainable-fisheries/catch-shares
Catch shares are management strategies that allocate a portion of the total allowable fishery catch to individuals, cooperatives, communities or other entities, who may not take more than their share. Individual fishing quotas are one type. Territorial use rights for fisheries (TURFs) give an exclusive right to fish a designated area. NOAA says there are currently 17 catch share programs across the country.

## bycatch | Bycatch, catch limits and aquaculture
type: term
keywords: bycatch, discards, catch limit, what is aquaculture, what is bycatch
retrieved: 2026-10-28
source: https://www.fisheries.noaa.gov/national/sustainable-seafood/glossary-sustainable-seafood
Per NOAA's glossary, bycatch is the discarded catch of any living marine resource plus unobserved mortality due to a direct encounter with fishing gear. A catch limit is the weight limit on fish that fishermen can catch in a fishing season. Aquaculture is the breeding, rearing and harvesting of plants and animals in natural and human-made water environments, also called fish or shellfish farming.

## mrip | How recreational catch is estimated (MRIP)
type: method
keywords: mrip, recreational catch, recreational data, angler survey, how is recreational estimated, pse, recreational estimates reliable
retrieved: 2026-10-28
source: https://www.fisheries.noaa.gov/insight/marine-recreational-information-program
MRIP is a NOAA state-regional-federal partnership that surveys saltwater anglers. Catch rate comes from in-person dockside interviews; effort comes from a mail survey (private boat and shore anglers) and a phone survey (for-hire captains). Total catch is catch rate times effort. Estimates are sample-based: MRIP cautions use when the percent standard error (PSE) is over 30 and does not support use when it exceeds 50. NOAA says MRIP is being replaced by a new recreational data framework.

## gear_types | Commercial fishing gear types
type: gear
keywords: gear, trawl, longline, gillnet, pot, trap, purse seine, dredge, hook and line, turtle excluder, ted, how are fish caught
retrieved: 2026-10-28
source: https://www.fisheries.noaa.gov/national/bycatch/fishing-gear-and-risks-protected-species
NOAA groups gear as trawls (bottom, midwater, skimmer), longlines (bottom, pelagic), gillnets, pots and traps (including pound nets), purse seines, and others such as dredges, buoy gear and hook and line. Fishermen use particular gear to target particular species. Turtle excluder devices are currently required only in trawl fisheries targeting shrimp and summer flounder.

## seafood_names | Market names and labeling (FDA Seafood List)
type: labeling
keywords: seafood list, market name, acceptable name, common name, mislabeled, mislabeling, misbranding, label, labeling, what can it be called
retrieved: 2026-10-28
source: https://www.fda.gov/media/171514/download
FDA's Seafood List gives nonbinding guidance on acceptable market and common names for seafood sold in the U.S. A market name should identify the species without being confusingly similar to another species. Regional vernacular names are generally not acceptable and may cause misbranding. A misleading name can hide food safety hazards such as allergens or natural toxins and cause economic fraud when similar species have different market values.

## histamine | Histamine (scombrotoxin) and keeping tuna cold
type: handling
keywords: histamine, scombrotoxin, scombroid, tuna, mahi, keep cold, chill, temperature abuse, spoilage, how cold, storage, handling, safe to eat
retrieved: 2026-10-28
source: https://www.fda.gov/media/182955/download
Tuna and mahi-mahi can form histamine if not chilled promptly after death. FDA says once histamine forms it cannot reliably be removed by washing, freezing or heating. In studies it cites, freshly caught mahi-mahi held at 26 C (78.8 F) for 9 hours or more stayed under 5 ppm histamine, while fish held at about 24 C (75 F) or warmer reached levels above 35 ppm. This source gives no numeric storage limit; see FDA's Hazards and Controls Guide for those.

## us_supply | U.S. seafood supply and imports
type: market
keywords: imports, imported, import, import share, per capita, consumption, how much seafood do americans eat, domestic vs imported
retrieved: 2026-10-28
source: https://www.fisheries.noaa.gov/national/sustainable-fisheries/fisheries-united-states
NOAA's Fisheries of the United States page gives preliminary 2023 figures of 19.1 pounds of seafood eaten per person and an estimated 80 percent of seafood eaten coming from imports. These are preliminary and subject to revision. Landings in the NOAA landings file cover only U.S. catch, not what is imported.

## seasons | Fishing seasons and fishing years
type: rules
keywords: season, fishing year, when is the season, closed season, open season, when can you fish, opens, closes
retrieved: 2026-10-28
source: https://www.fisheries.noaa.gov/species/american-lobster https://www.fisheries.noaa.gov/species/atlantic-sea-scallop https://www.fisheries.noaa.gov/species/pacific-halibut
Seasons are set per fishery. The federal American lobster fishing year runs May 1 to April 30. The Atlantic sea scallop fishing year begins April 1. The commercial Pacific halibut season, set by the International Pacific Halibut Commission, usually runs March to November. NOAA landings are annual, so they cannot show season timing.

## stock_american_lobster | American lobster: stock status and rules
type: stock
species: american lobster, lobster
keywords: lobster status, lobster overfished, lobster rules, lobster management, v-notch, lobster sustainability
retrieved: 2026-10-28
source: https://www.fisheries.noaa.gov/species/american-lobster
Per the 2025 ASMFC assessment: Gulf of Maine/Georges Bank is not overfished but subject to overfishing; Southern New England is overfished and not subject to overfishing, and is considered severely depleted. Fishing is controlled by trap limits, not quotas. Egg-bearing females may not be harvested and must be v-notched in most areas. Lobsters must be landed live and whole. Seven lobster management areas apply.

## stock_atlantic_cod | Atlantic cod: stock status and rules
type: stock
species: atlantic cod, cod
keywords: cod status, cod overfished, cod rebuilding, cod management, cod sustainability
retrieved: 2026-10-28
source: https://www.fisheries.noaa.gov/species/atlantic-cod
Per the 2021 assessment, both the Gulf of Maine and Georges Bank stocks are overfished and subject to overfishing. Rebuilding target dates are 2033 for Gulf of Maine and 2026 for Georges Bank. Cod is one of 13 groundfish managed under the Northeast Multispecies plan, with permits, closures, minimum sizes, annual catch limits and an optional sector (catch share) program. Georges Bank cod is co-managed with Canada.

## stock_haddock | Haddock: stock status and rules
type: stock
species: haddock
keywords: haddock status, haddock overfished, haddock management, haddock sustainability
retrieved: 2026-10-28
source: https://www.fisheries.noaa.gov/species/haddock
Per 2024 assessments, both the Gulf of Maine and Georges Bank haddock stocks are not overfished and not subject to overfishing. Haddock is managed with 12 other groundfish under the Northeast Multispecies plan. Georges Bank is co-managed with Canada.

## stock_pacific_halibut | Pacific halibut: stock status and rules
type: stock
species: pacific halibut, halibut
keywords: halibut status, halibut overfished, halibut management, halibut quota, iphc
retrieved: 2026-10-28
source: https://www.fisheries.noaa.gov/species/pacific-halibut
Per the 2024 assessment the stock is not overfished and not subject to overfishing. The U.S. and Canada have managed it through the International Pacific Halibut Commission since 1923; the IPHC sets annual catch limits and season dates. In Alaska the fishery uses the Individual Fishing Quota and Community Development Quota programs. NOAA says about 95 percent of the 2024 harvest was landed in Alaska.

## stock_alaska_pollock | Alaska pollock: stock status and rules
type: stock
species: alaska pollock, walleye pollock, pollock
keywords: pollock status, pollock overfished, pollock management, pollock quota, pollock sustainability
retrieved: 2026-10-28
source: https://www.fisheries.noaa.gov/species/alaska-pollock
Aleutian Islands, Eastern Bering Sea and Western/Central/West Yakutat Gulf of Alaska stocks are not overfished; population levels for Bogoslof and Southeast Gulf of Alaska are unknown. Not subject to overfishing. The U.S. manages five separate stocks. The Bering Sea fishery was one of the first with catch shares; Community Development Quota groups receive 10 percent of the Eastern Bering Sea total allowable catch.

## stock_sea_scallop | Atlantic sea scallop: stock status and rules
type: stock
species: atlantic sea scallop, sea scallop, scallop, scallops
keywords: scallop status, scallop overfished, scallop management, scallop size, scallop sustainability
retrieved: 2026-10-28
source: https://www.fisheries.noaa.gov/species/atlantic-sea-scallop
Per a 2020 assessment the stock is not overfished and not subject to overfishing. Catch limits are divided among fleet groups through days-at-sea and access area trips, area closures protect young scallops, and vessels use vessel monitoring systems. The minimum in-shell size is 3.5 inches shell height. The 2026 fishery catch limit is 12,028 metric tons.

## stock_summer_flounder | Summer flounder: stock status and rules
type: stock
species: summer flounder, fluke, flounder
keywords: flounder status, fluke status, flounder overfished, flounder quota, flounder management, summer flounder sustainability
retrieved: 2026-10-28
source: https://www.fisheries.noaa.gov/species/summer-flounder/seafood
Per the 2025 assessment summer flounder is not overfished and not subject to overfishing. The minimum commercial size is 14 inches total length and a permit is required to sell or buy it. The 2026 commercial quota is 12.78 million pounds, with allocation 60 percent commercial and 40 percent recreational.

## stock_sockeye_salmon | Sockeye salmon: stock status and rules
type: stock
species: sockeye salmon, sockeye, red salmon, salmon
keywords: sockeye status, salmon status, salmon overfished, salmon management, salmon escapement, salmon sustainability
retrieved: 2026-10-28
source: https://www.fisheries.noaa.gov/species/sockeye-salmon
Alaska has hundreds of sockeye stocks; some are in decline, others steady or increasing, and none are listed under the Endangered Species Act. On the West Coast one population was listed as endangered and one as threatened as of 2019. Overfishing status is unknown but management measures are in place. Harvest is set from escapement goals using in-season estimates of returning fish. Sockeye mature at about age 5 and die within weeks of spawning.

## fresh_handling | Buying, storing and cooking fish (FDA consumer advice)
type: handling
keywords: fresh fish, is fresh, fish is fresh, know if fish, how to tell fresh, buy fresh, freshness, how long keep fish, refrigerator, fridge, freezer, freeze fish, cook to, internal temperature, 145, live crab, live lobster, clams, mussels, oysters, tap test
retrieved: 2026-10-28
source: https://www.fda.gov/food/buy-store-serve-safe-food/selecting-and-serving-fresh-and-frozen-seafood-safely
FDA says fresh fish should smell mild with clear, shiny eyes; fillets should be firm and spring back when pressed, and color alone does not show freshness. Buy fish only if refrigerated or on a thick bed of fresh ice. Keep the refrigerator at 40 F or below; refrigerate fish used within 2 days, otherwise wrap tightly and freeze. Cook most seafood to 145 F. Live crabs and lobsters should show leg movement; live clams, oysters and mussels should close when tapped.

## simp | Seafood Import Monitoring Program (SIMP)
type: rules
keywords: simp, seafood import monitoring, traceability, illegal fishing, iuu, imported seafood rules, import rules, covered species
retrieved: 2026-10-28
source: https://www.fisheries.noaa.gov/international/international-affairs/seafood-import-monitoring-program
SIMP is a risk-based NOAA traceability program with reporting and recordkeeping requirements for seafood imports, meant to keep illegal, unreported, unregulated and misrepresented seafood out of U.S. commerce. Importers report data from harvest to entry. It covers 13 groups: abalone, Atlantic cod, Atlantic blue crab, dolphinfish (mahi mahi), grouper, red king crab, Pacific cod, red snapper, sea cucumber, sharks, shrimp, swordfish and tuna. Shrimp and abalone were added on December 31, 2018; the rest started January 1, 2018.

## aquaculture_share | Farmed seafood in the U.S. supply
type: market
keywords: farmed, farm raised, farmed seafood, aquaculture, fish farming, aquaculture share, seafood supply, wild vs farmed, wild-caught, wild caught, oyster farming, how much is farmed, import share, trade deficit
retrieved: 2026-10-28
source: https://www.fisheries.noaa.gov/national/aquaculture/us-aquaculture
NOAA says marine aquaculture is about 7 percent of U.S. domestic seafood production by weight and about 24 percent by value (Fisheries of the United States, 2020). Oysters, clams and mussels are over 80 percent of marine aquaculture value, with salmon and shrimp most of the rest. The page says the U.S. imports 70 to 85 percent of its seafood, more than half of it from foreign aquaculture, and the 2020 seafood trade deficit reached $17 billion. NOAA landings cover wild catch only.

## fisheries_management | How U.S. fisheries are managed
type: rules
keywords: how are fisheries managed, magnuson-stevens, magnuson stevens, fishery management council, councils, fishery management plan, fmp, annual catch limit, federal waters, state waters, eez, stock assessment, who regulates fishing
retrieved: 2026-10-28
source: https://www.fisheries.noaa.gov/insight/understanding-fisheries-management-united-states
NOAA Fisheries manages the U.S. exclusive economic zone, 3 to 200 nautical miles offshore; states generally manage waters out to 3 miles. The Magnuson-Stevens Act guides this: prevent overfishing, rebuild overfished stocks, and keep seafood supply sustainable. Eight regional fishery management councils write fishery management plans and set annual catch limits using the best available science. Stock assessments judge each stock against MSY, and overfished or overfishing stocks trigger rebuilding plans.

## farmed_atlantic_salmon | Farmed Atlantic salmon in the U.S.
type: farming
species: atlantic salmon, salmon, farmed salmon
keywords: farmed salmon, farmed atlantic salmon, salmon farming, disease, diseases, prevented, how is salmon farmed, how is atlantic salmon farmed, net pens, net pen, sea lice, salmon farm, fallowing, hatchery, smolt, farm disease, antibiotics, vaccines
retrieved: 2026-10-28
source: https://www.fisheries.noaa.gov/species/atlantic-salmon-farmed
NOAA says U.S. farmed Atlantic salmon comes mostly from Maine and Washington, and most Atlantic salmon sold in the U.S. is imported. Eggs hatch in freshwater tanks on land for about a year, then fish grow in coastal net pens for about two years. Feed typically contains fish meal, fish oil, vitamins and minerals, with plant-based alternatives replacing some. Disease is managed with vaccines, health monitoring and low stocking density; antibiotics are not used preventively. Sea lice are controlled with hydrogen peroxide, warm-water delousing, cleaner wrasses and fallowing.

## aquaculture_feeds | What farmed fish eat (aquaculture feeds)
type: farming
keywords: what do farmed fish eat, fish feed, aquaculture feed, aquafeed, feeds, fishmeal, fish meal, fish oil, pellets, feed cost, alternative feeds, insects, algae, what do farmed salmon eat, eat
retrieved: 2026-10-28
source: https://www.fisheries.noaa.gov/insight/feeds-aquaculture
NOAA says farm feed is usually dried pellets supplying about 40 essential nutrients. Carnivorous fish such as salmon were traditionally fed diets of 30 to 50 percent fishmeal and oil, though these are not required; fishmeal in salmon diets fell from about 70 percent in 1980 to about 25 percent in 2017. About 70 percent of fishmeal and oil comes from small fish such as anchovies, herring and menhaden, the rest from processing scraps. Feed is about 60 percent of the cost of growing fish.

## shellfish_aquaculture | Farmed oysters, clams and mussels
type: farming
species: eastern oyster, pacific oyster, oyster, oysters, clam, clams, mussel, mussels, blue mussel
keywords: farmed oysters, oyster farming, shellfish farming, shellfish aquaculture, farmed clams, farmed mussels, how much shellfish is farmed, oyster farm
retrieved: 2026-10-28
source: https://www.fisheries.noaa.gov/insight/understanding-shellfish-aquaculture
NOAA reports U.S. marine shellfish aquaculture in 2023 produced 28.1 million pounds of oysters, 8 million pounds of clams and 650,000 pounds of mussels, with an estimated value of $294.6 million. The concerns NOAA lists for shellfish farming include water quality degradation, habitat degradation and the spread of harmful algal blooms.

## west_coast_finfish_farming | Fish farming on the U.S. West Coast
type: farming
keywords: west coast, fish farming on the west coast, west coast fish farming, west coast aquaculture, washington salmon farming, net pens washington, oregon fish farm, california fish farm, steelhead farming, coho farming, west coast salmon farm
retrieved: 2026-10-28
source: https://www.fisheries.noaa.gov/west-coast/aquaculture/commercial-finfish-aquaculture-west-coast
NOAA says commercial finfish farming on the West Coast covers coho salmon, steelhead and rainbow trout, and Atlantic salmon; Chinook, chum, pink and sockeye are raised only for enhancement or restoration. Washington has produced salmon commercially for about 40 years, while Oregon and California have no commercial salmon production. The page says Washington is phasing out commercial net-pen culture of Atlantic salmon by 2022. The sector produces about 20 million pounds of fish a year and employs about 200 people.

## dungeness_crab_management | Dungeness crab: who manages it and when the season opens
type: stock
species: dungeness crab
keywords: dungeness season, crab season, when does crab season open, dungeness crab season, dungeness management, dungeness rules, meat fill, pre-season testing, tri-state, dungeness crab rules, season opening
retrieved: 2026-10-29
source: https://www.psmfc.org/program/tri-state-dungeness-crab-tsdc/?pid=17
The commercial Dungeness crab fishery off California, Oregon and Washington is managed by the three state fish and wildlife agencies, which consult through the Pacific States Marine Fisheries Commission's Tri-State process. The season normally opens December 1. Pre-season meat pick-out testing decides whether it opens then; if crab are not ready, the states delay the opening and announce a new date after more testing. Size, sex and pot rules are set by each state, so check the state agency for those.

## west_coast_groundfish_catch_shares | West Coast groundfish trawl catch shares
type: rules
keywords: west coast groundfish, groundfish trawl, trawl rationalization, shorebased ifq, west coast catch share, groundfish quota, observer coverage, catch monitors, rockfish quota, west coast trawl
retrieved: 2026-10-29
source: https://www.fisheries.noaa.gov/west-coast/sustainable-fisheries/west-coast-groundfish-trawl-catch-share-program
NOAA implemented a catch share program for the West Coast groundfish trawl fishery in 2011: an individual fishing quota (IFQ) program for the shorebased trawl fleet and cooperatives for the at-sea mothership and catcher/processor fleets. 138 quota share permits were first issued based on past catch. Shorebased IFQ vessels must carry an observer at all times at sea, and catch monitors must be present at first receivers for the whole landing.

## stock_sablefish | Sablefish (black cod): stock status and rules
type: stock
species: sablefish, black cod
keywords: sablefish status, black cod status, sablefish overfished, sablefish management, sablefish quota, black cod
retrieved: 2026-10-29
source: https://www.fisheries.noaa.gov/species/sablefish
Also sold as black cod or butterfish. The Alaska stock (Bering Sea, Aleutian Islands, Gulf of Alaska) is not overfished (2024 assessment) and the Pacific coast stock is not overfished (2025 assessment); neither is subject to overfishing. In Alaska, fixed gear (longlines and pots) takes about 90 percent of the quota, mostly under individual fishing quotas. On the West Coast it is managed with coast-wide catch limits, daily trip limits for some vessels, and IFQs for the trawl fishery.

## stock_blue_crab | Blue crab: stock status and rules
type: stock
species: blue crab, callinectes sapidus
keywords: blue crab management, blue crab overfished, blue crab quota, blue crab rules, blue crab season, blue crab status, blue crab stock, blue crab sustainable
retrieved: 2026-10-29
source: https://www.fisheries.noaa.gov/species/blue-crab
NOAA's page gives no formal overfished rating: blue crab numbers swing widely from year to year, and the Chesapeake Bay is judged against reference points for females set in a 2011 benchmark assessment and checked by annual winter dredge surveys. The Bay fishery is managed by Maryland, Virginia and the Potomac River Fisheries Commission, not NOAA. Recreational seasons differ: Maryland April 1 to December 15, the Potomac April 1 to November 30, Virginia year-round with some gear limits.

## stock_white_shrimp | White shrimp: stock status and rules
type: stock
species: northern white shrimp, white shrimp
keywords: northern white shrimp management, northern white shrimp overfished, northern white shrimp quota, northern white shrimp rules, northern white shrimp season, northern white shrimp status, northern white shrimp stock, northern white shrimp sustainable, white shrimp management, white shrimp overfished, white shrimp quota, white shrimp rules, white shrimp season, white shrimp status, white shrimp stock, white shrimp sustainable
retrieved: 2026-10-29
source: https://www.fisheries.noaa.gov/species/white-shrimp
Both stocks are not overfished and not subject to overfishing (Gulf 2019 assessment, South Atlantic 2018). NOAA and the South Atlantic and Gulf councils manage federal waters, setting catch levels from historic harvest and fishing rates. Otter trawlers must use sea turtle excluder devices, and federal waters off Texas close each year from about mid-May to mid-July to protect brown shrimp.

## stock_brown_shrimp | Brown shrimp: stock status and rules
type: stock
species: brown shrimp
keywords: brown shrimp management, brown shrimp overfished, brown shrimp quota, brown shrimp rules, brown shrimp season, brown shrimp status, brown shrimp stock, brown shrimp sustainable
retrieved: 2026-10-29
source: https://www.fisheries.noaa.gov/species/brown-shrimp
The Gulf (2019) and South Atlantic (2018) stocks are not overfished and not subject to overfishing. NOAA and the South Atlantic and Gulf councils manage federal waters and state agencies manage inshore waters. Federal waters off Texas close each year from about mid-May to mid-July, and otter trawl shrimpers must use turtle excluder devices.

## stock_pacific_cod | Pacific cod: stock status and rules
type: stock
species: pacific cod
keywords: pacific cod management, pacific cod overfished, pacific cod quota, pacific cod rules, pacific cod season, pacific cod status, pacific cod stock, pacific cod sustainable
retrieved: 2026-10-29
source: https://www.fisheries.noaa.gov/species/pacific-cod
The Bering Sea, Aleutian Islands and Gulf of Alaska stocks are not overfished (2024 assessments) and not subject to overfishing; the Pacific coast stock has never been formally assessed. NOAA and the North Pacific council manage Alaska, the Pacific council the West Coast. Alaska fishermen need limited-entry permits, quotas are split by gear type and processing sector, and all Pacific cod caught must be kept.

## stock_atlantic_menhaden | Atlantic menhaden: stock status and rules
type: stock
species: menhadens, atlantic menhaden, menhaden, bunker
keywords: atlantic menhaden management, atlantic menhaden overfished, atlantic menhaden quota, atlantic menhaden rules, atlantic menhaden season, atlantic menhaden status, atlantic menhaden stock, atlantic menhaden sustainable, menhadens management, menhadens overfished, menhadens quota, menhadens rules, menhadens season, menhadens status, menhadens stock, menhadens sustainable
retrieved: 2026-10-29
source: https://www.fisheries.noaa.gov/species/atlantic-menhaden
The 2025 assessment found Atlantic menhaden not overfished, with no overfishing. The Atlantic States Marine Fisheries Commission sets a coastwide total allowable catch and allocates it among states, and a Chesapeake Bay harvest cap (set 2006, lowered 2017) limits catch there. Menhaden are processed into fish meal and fish oil and used as bait in the blue crab and lobster fisheries.

## stock_red_snapper | Red snapper: stock status and rules
type: stock
species: red snapper
keywords: red snapper management, red snapper overfished, red snapper quota, red snapper rules, red snapper season, red snapper status, red snapper stock, red snapper sustainable
retrieved: 2026-10-29
source: https://www.fisheries.noaa.gov/species/red-snapper
The Gulf stock is not overfished but still rebuilding (2018 assessment) and not subject to overfishing; the South Atlantic stock is not overfished and not subject to overfishing (2024 assessment). NOAA manages it with the Gulf and South Atlantic councils. Gulf commercial fishermen need a permit and fish under an individual fishing quota, with catch limits, a minimum size and bag limits; the South Atlantic follows a rebuilding plan with a 2044 goal.

## stock_red_king_crab | Red king crab: stock status and rules
type: stock
species: king crab, red king crab
keywords: king crab management, king crab overfished, king crab quota, king crab rules, king crab season, king crab status, king crab stock, king crab sustainable, red king crab management, red king crab overfished, red king crab quota, red king crab rules, red king crab season, red king crab status, red king crab stock, red king crab sustainable
retrieved: 2026-10-29
source: https://www.fisheries.noaa.gov/species/red-king-crab
Bristol Bay, Pribilof Islands and Norton Sound stocks are not overfished (2025 assessments) and not subject to overfishing; the Western Aleutian stock's status is unknown. NOAA, the North Pacific council and Alaska Department of Fish and Game manage it with size, sex and season rules, and a 2005 crab rationalization program shares harvest among fishermen, processors and communities. The Pribilof fishery has been closed since 1999, and Bristol Bay was closed for the 2021/22 and 2022/23 seasons.

## stock_snow_crab | Alaska snow crab: stock status and rules
type: stock
species: snow crab, opilio
keywords: alaska snow crab management, alaska snow crab overfished, alaska snow crab quota, alaska snow crab rules, alaska snow crab season, alaska snow crab status, alaska snow crab stock, alaska snow crab sustainable, snow crab management, snow crab overfished, snow crab quota, snow crab rules, snow crab season, snow crab status, snow crab stock, snow crab sustainable
retrieved: 2026-10-29
source: https://www.fisheries.noaa.gov/species/alaska-snow-crab
The 2025 assessment found the stock overfished but rebuilding, with a 2029 target, and not subject to overfishing. The fishery was closed for the 2022 and 2023 fishing years (each runs July 1 to June 30), so there were no commercial landings in 2024. It is managed by size, sex and season (males of a set size only), under the 2005 crab rationalization program with 10 percent for community development quotas; observers cover 20 percent of vessels.

## stock_pink_salmon | Pink salmon: stock status and rules
type: stock
species: pink salmon, humpy
keywords: pink salmon management, pink salmon overfished, pink salmon quota, pink salmon rules, pink salmon season, pink salmon status, pink salmon stock, pink salmon sustainable
retrieved: 2026-10-29
source: https://www.fisheries.noaa.gov/species/pink-salmon
NOAA calls pink salmon the most abundant Pacific salmon in Alaska; West Coast status is unknown. Alaska sets harvests from escapement goals so enough fish return to spawn, with federal-waters management delegated to the state. Pink salmon live two years, so returns are much larger in odd-numbered years and harvest limits are usually raised then.

## stock_chinook_salmon | Chinook (king) salmon: stock status and rules
type: stock
species: chinook salmon, king salmon, chinook
keywords: chinook management, chinook overfished, chinook quota, chinook rules, chinook salmon management, chinook salmon overfished, chinook salmon quota, chinook salmon rules, chinook salmon season, chinook salmon status, chinook salmon stock, chinook salmon sustainable, chinook season, chinook status, chinook stock, chinook sustainable
retrieved: 2026-10-29
source: https://www.fisheries.noaa.gov/species/chinook-salmon
In Alaska stock status varies and none are listed under the Endangered Species Act; on the West Coast, as of 2025, two populations are endangered and seven threatened. The Pacific council manages West Coast Chinook under the Pacific Coast Salmon Plan, with size limits, seasons, quotas and gear rules reset each year by abundance. Alaska sets harvests from escapement goals, and the Pacific Salmon Treaty covers stocks shared with Canada.

## stock_chum_salmon | Chum salmon: stock status and rules
type: stock
species: chum salmon, keta, dog salmon
keywords: chum salmon management, chum salmon overfished, chum salmon quota, chum salmon rules, chum salmon season, chum salmon status, chum salmon stock, chum salmon sustainable
retrieved: 2026-10-29
source: https://www.fisheries.noaa.gov/species/chum-salmon/overview
As of 2025 Alaska had hundreds of chum stocks; some are declining and others steady or increasing, and none are ESA-listed. On the West Coast two populations are listed as threatened. Alaska manages harvest from escapement goals; the Pacific council manages West Coast chum.

## stock_pacific_bigeye_tuna | Pacific bigeye tuna: stock status and rules
type: stock
species: bigeye tuna, pacific bigeye tuna, ahi
keywords: bigeye tuna management, bigeye tuna overfished, bigeye tuna quota, bigeye tuna rules, bigeye tuna season, bigeye tuna status, bigeye tuna stock, bigeye tuna sustainable, pacific bigeye tuna management, pacific bigeye tuna overfished, pacific bigeye tuna quota, pacific bigeye tuna rules, pacific bigeye tuna season, pacific bigeye tuna status, pacific bigeye tuna stock, pacific bigeye tuna sustainable
retrieved: 2026-10-29
source: https://www.fisheries.noaa.gov/species/pacific-bigeye-tuna
The Western and Central Pacific stock (2023 assessment) and the Eastern Pacific stock (2024 assessment) are not overfished and not subject to overfishing. The WCPFC and IATTC manage it internationally and NOAA applies their rules. Longline fishing is banned within 200 miles of the U.S. West Coast, and permits for the Hawaii and American Samoa longline fleets are limited.

## stock_pacific_albacore | Pacific albacore tuna: stock status and rules
type: stock
species: albacore tuna, albacore, pacific albacore
keywords: albacore tuna management, albacore tuna overfished, albacore tuna quota, albacore tuna rules, albacore tuna season, albacore tuna status, albacore tuna stock, albacore tuna sustainable, pacific albacore tuna management, pacific albacore tuna overfished, pacific albacore tuna quota, pacific albacore tuna rules, pacific albacore tuna season, pacific albacore tuna status, pacific albacore tuna stock, pacific albacore tuna sustainable
retrieved: 2026-10-29
source: https://www.fisheries.noaa.gov/species/pacific-albacore-tuna
The North Pacific stock (2023 assessment) and South Pacific stock (2021) are not overfished and not subject to overfishing. The IATTC and WCPFC manage it internationally on scientific advice from the ISC. West Coast fishermen mostly use troll and pole-and-line gear, which NOAA says has insignificant bycatch based on limited observer data.

## stock_pacific_whiting | Pacific whiting (hake): stock status and rules
type: stock
species: pacific (whiting) hake, pacific whiting, pacific hake, whiting, hake
keywords: pacific (whiting) hake management, pacific (whiting) hake overfished, pacific (whiting) hake quota, pacific (whiting) hake rules, pacific (whiting) hake season, pacific (whiting) hake status, pacific (whiting) hake stock, pacific (whiting) hake sustainable, pacific whiting management, pacific whiting overfished, pacific whiting quota, pacific whiting rules, pacific whiting season, pacific whiting status, pacific whiting stock, pacific whiting sustainable
retrieved: 2026-10-29
source: https://www.fisheries.noaa.gov/species/pacific-whiting
The coastal stock is not overfished and not subject to overfishing (2024 assessment). The U.S. and Canada share it under the Pacific Whiting Agreement, about 74 percent of the quota to the U.S. and 26 percent to Canada. U.S. catch is split among shore-based, mothership, catcher-processor and tribal sectors, and shore-based trawlers fish under the trawl catch share program.

## stock_caribbean_spiny_lobster | Caribbean spiny lobster: stock status and rules
type: stock
species: caribbean spiny lobster, spiny lobster, florida lobster
keywords: caribbean spiny lobster management, caribbean spiny lobster overfished, caribbean spiny lobster quota, caribbean spiny lobster rules, caribbean spiny lobster season, caribbean spiny lobster status, caribbean spiny lobster stock, caribbean spiny lobster sustainable
retrieved: 2026-10-29
source: https://www.fisheries.noaa.gov/species/caribbean-spiny-lobster/overview
Puerto Rico, St. Thomas/St. John and St. Croix stocks are not overfished (2022), but the Puerto Rico stock is subject to overfishing; the South Atlantic/Gulf stock's population level is unknown (2005 assessment). Management is shared by NOAA, Florida, Puerto Rico, the U.S. Virgin Islands and three councils. The Gulf and South Atlantic season is closed April 1 through August 5, and Caribbean federal waters have a 3.5-inch minimum size.

## stock_atlantic_yellowfin | Atlantic yellowfin tuna: stock status and rules
type: stock
species: yellowfin tuna, atlantic yellowfin tuna, yellowfin
keywords: atlantic yellowfin tuna management, atlantic yellowfin tuna overfished, atlantic yellowfin tuna quota, atlantic yellowfin tuna rules, atlantic yellowfin tuna season, atlantic yellowfin tuna status, atlantic yellowfin tuna stock, atlantic yellowfin tuna sustainable, yellowfin tuna management, yellowfin tuna overfished, yellowfin tuna quota, yellowfin tuna rules, yellowfin tuna season, yellowfin tuna status, yellowfin tuna stock, yellowfin tuna sustainable
retrieved: 2026-10-29
source: https://www.fisheries.noaa.gov/species/atlantic-yellowfin-tuna
The 2024 assessment found the stock not overfished and not subject to overfishing. It is managed internationally through ICCAT. U.S. commercial and recreational fishermen need a permit, and the fishery uses gear restrictions, time and area closures and a minimum size; U.S. landings are a small share of the international catch.

## stock_north_atlantic_swordfish | North Atlantic swordfish: stock status and rules
type: stock
species: swordfish, north atlantic swordfish
keywords: north atlantic swordfish management, north atlantic swordfish overfished, north atlantic swordfish quota, north atlantic swordfish rules, north atlantic swordfish season, north atlantic swordfish status, north atlantic swordfish stock, north atlantic swordfish sustainable, swordfish management, swordfish overfished, swordfish quota, swordfish rules, swordfish season, swordfish status, swordfish stock, swordfish sustainable
retrieved: 2026-10-29
source: https://www.fisheries.noaa.gov/species/north-atlantic-swordfish
The 2022 assessment found the stock not overfished and not subject to overfishing. ICCAT assesses Atlantic swordfish and NOAA sets U.S. rules from its recommendations and domestic science. Pelagic longline and some handgear permits are limited access, annual catch limits apply, and fishermen must use large circle hooks to reduce sea turtle bycatch.

## stock_market_squid | California market squid: stock status and rules
type: stock
species: california market squid, market squid
keywords: california market squid management, california market squid overfished, california market squid quota, california market squid rules, california market squid season, california market squid status, california market squid stock, california market squid sustainable
retrieved: 2026-10-29
source: https://www.fisheries.noaa.gov/species/california-market-squid
Population level and overfishing status are unknown, but management measures are in place. California's Fish and Game Commission and Department of Fish and Wildlife manage it under the state Market Squid Fishery Management Plan, with seasonal catch limits, weekend closures for uninterrupted spawning, and limits on using lights near several Channel Islands to protect nesting seabirds.

## stock_atlantic_striped_bass | Atlantic striped bass: stock status and rules
type: stock
species: striped bass, atlantic striped bass, rockfish striper, striper
keywords: atlantic striped bass management, atlantic striped bass overfished, atlantic striped bass quota, atlantic striped bass rules, atlantic striped bass season, atlantic striped bass status, atlantic striped bass stock, atlantic striped bass sustainable, striped bass management, striped bass overfished, striped bass quota, striped bass rules, striped bass season, striped bass status, striped bass stock, striped bass sustainable
retrieved: 2026-10-29
source: https://www.fisheries.noaa.gov/species/atlantic-striped-bass
The 2024 assessment found the stock overfished but not subject to overfishing, and it is under a rebuilding plan. The Atlantic States Marine Fisheries Commission manages it from Maine to Virginia and coastal North Carolina. Federal waters (3 to 200 miles) are closed to all commercial and recreational striped bass fishing; state waters use quotas, minimum sizes and seasonal closures.

## stock_eastern_oyster | Eastern oyster: stock status and rules
type: stock
species: eastern oyster
keywords: eastern oyster management, eastern oyster overfished, eastern oyster quota, eastern oyster rules, eastern oyster season, eastern oyster status, eastern oyster stock, eastern oyster sustainable
retrieved: 2026-10-29
source: https://www.fisheries.noaa.gov/species/eastern-oyster
NOAA says wild eastern oyster populations have dwindled to a few percent of their former size; in Chesapeake Bay they are 1 to 2 percent of historic levels, after disease, overharvesting, habitat loss and poor water quality. States manage the wild harvest and permit oyster farms; farmed oysters need no feed. NOAA and partners have restored about 1,100 acres of reef in Maryland and Virginia.
