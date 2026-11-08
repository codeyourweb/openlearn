"""Second batch of demo themes: numbers, environment, economy, languages, music, nutrition.

Split from ``build_content`` so the reviewed fact sheets stay readable in small
files. Same shape: a wiki with a few sections, fifteen facts, one deck.
"""

from __future__ import annotations

from typing import Any

EXTRA_THEMES: list[dict[str, Any]] = [
    {
        "key": "math",
        "language": "en",
        "title": "Everyday mathematics",
        "description": "Percentages, proportions, probability and the arithmetic that settles arguments.",
        "sections": [
            (
                "Percentages",
                "A percentage is a fraction of a hundred, which makes comparisons possible but "
                "also hides the base. A twenty percent rise followed by a twenty percent fall "
                "does not return to the starting value: the second percentage applies to a "
                "larger number.",
            ),
            (
                "Probability",
                "Probability counts possibilities, not intentions. Two independent events "
                "multiply, which is why a rare accident becomes likely across many attempts, "
                "and why a coin has no memory of its last result.",
            ),
            (
                "Estimating",
                "A quick estimate catches most arithmetic mistakes before they cause damage. "
                "Rounding to one significant figure and checking the order of magnitude is "
                "usually enough to see whether a figure is plausible.",
            ),
        ],
        "facts": [
            ("What does a percentage express?", "A fraction of a hundred", ["A ratio of two", "A decimal fraction of ten", "A fixed unit"], "It makes comparisons easier."),
            ("A 20% rise after a 20% fall: where are you?", "Below the starting value", ["Exactly at the start", "Above the start", "Impossible to know"], "The fall applies to a larger number."),
            ("How do you combine two independent probabilities?", "Multiply them", ["Add them", "Average them", "Subtract them"], "Two coin flips: half of a half."),
            ("What is the median?", "The middle value of a sorted list", ["The most frequent value", "The average", "The largest value"], "It resists extreme values."),
            ("What does a 1-in-1000 risk mean?", "About one case per thousand people", ["One case per million", "One case in total", "One case per hundred"], "The base matters more than the ratio."),
            ("What is the mean of 2, 4 and 9?", "5", ["4", "6", "7"], "Add and divide by the count."),
            ("Why estimate before calculating exactly?", "It catches order-of-magnitude errors", ["It saves paper", "It avoids fractions", "It replaces algebra"], "Rounding to one figure is enough."),
            ("What is a proportion?", "A statement that two ratios are equal", ["A single fraction", "A percentage sum", "A square root"], "It allows scaling of recipes and maps."),
            ("If a car covers 120 km in 1.5 h, what is its average speed?", "80 km/h", ["60 km/h", "100 km/h", "120 km/h"], "Distance divided by time."),
            ("What does multiplication by a number below 1 do?", "Reduces the value", ["Increases it", "Keeps it equal", "Makes it negative"], "Percentages are decimals in disguise."),
            ("What is a prime number?", "A number with exactly two divisors", ["Any odd number", "A number ending in 3", "A number above ten"], "Two is the only even prime."),
            ("Why is correlation not causation?", "Two things can move together for a third reason", ["Correlation is always weak", "Causation cannot be measured", "Samples are too small"], "The cause may be a third factor."),
            ("What does rounding to two significant figures lose?", "Precision beyond the second digit", ["The sign", "The order of magnitude", "The unit"], "It keeps the size, not the detail."),
            ("If something doubles every day for 10 days, how much did it grow?", "About a thousand times", ["Ten times", "A hundred times", "A million times"], "2^10 is about 1024."),
            ("What is the quickest sanity check on a result?", "Compare it with an estimate you expect", ["Read it twice", "Ask a colleague", "Recalculate slowly"], "Plausibility is cheap and effective."),
        ],
    },
    {
        "key": "environment",
        "language": "en",
        "title": "Climate and resources",
        "description": "Greenhouse gases, water, energy and what a single person can change.",
        "sections": [
            (
                "The greenhouse effect",
                "Certain gases let sunlight through but absorb the heat the ground radiates "
                "back. That is what keeps the planet warm enough for life; adding more of "
                "those gases raises the temperature rather than creating a new phenomenon.",
            ),
            (
                "Water and land",
                "Fresh water is a small share of the total and unevenly distributed. Farming "
                "uses most of it, which is why irrigation efficiency and soil quality are "
                "climate questions as much as agricultural ones.",
            ),
            (
                "Energy",
                "A kilowatt-hour measures energy, a kilowatt measures power. Replacing a "
                "fossil source with a renewable one changes emissions, but the grid, storage "
                "and the timing of demand decide how much of it can actually be used.",
            ),
        ],
        "facts": [
            ("What makes CO2 a greenhouse gas?", "It absorbs infrared radiation and re-emits it", ["It reflects sunlight", "It destroys ozone", "It cools the stratosphere"], "More of it raises the surface temperature."),
            ("Which sector consumes the most fresh water?", "Agriculture", ["Industry", "Households", "Energy production"], "Irrigation dominates."),
            ("What is the difference between kW and kWh?", "Power versus energy over time", ["They are identical", "Energy versus power", "Voltage versus current"], "A kilowatt-hour is one kilowatt for an hour."),
            ("Why is fresh water a limited resource?", "Only a small share of water is fresh and reachable", ["It is destroyed by use", "Rivers dry up permanently", "Rainwater is unusable"], "Distribution matters as much as volume."),
            ("What does an energy transition need besides generation?", "Grids, storage and flexible demand", ["Cheaper panels only", "Fewer consumers", "Higher voltage"], "A supply is only useful if it arrives when needed."),
            ("What is biodiversity?", "The variety of living things in a place", ["The number of species in zoos", "The size of a population", "The health of one species"], "It supports resilience."),
            ("Why do trees help a city?", "They shade, cool air and slow storm water", ["They consume cars", "They replace drains", "They block wind only"], "Urban heat islands are measurable."),
            ("What is a carbon budget?", "The total emissions that fit a temperature limit", ["The cost of a policy", "The energy a country uses", "A fund for forests"], "It is spent once."),
            ("What does recycling save most effectively?", "The energy of making a material from scratch", ["The cost of transport", "The need for design", "The use of water entirely"], "Aluminium is the classic case."),
            ("Why does eating less meat reduce emissions?", "Livestock uses land and feed with high emissions", ["Meat is processed in factories", "Animals breathe too much", "Transport dominates"], "The effect varies by production method."),
            ("What is an urban heat island?", "A city district warmer than its surroundings", ["A city built on a volcano", "A tropical suburb", "A district without water"], "Concrete stores heat during the day."),
            ("Why is insulation an energy measure?", "It reduces the energy needed to keep a building comfortable", ["It generates electricity", "It filters air", "It adds humidity"], "It is usually the cheapest first step."),
            ("What happens to coastal land as sea levels rise?", "Salt water intrudes and low land floods more often", ["Rivers flow faster inland", "Mountains erode faster", "Rain becomes rare"], "Groundwater becomes unusable."),
            ("What is the precautionary principle?", "Act against a risk before certainty arrives", ["Wait for proof", "Ban all innovation", "Let the market decide"], "It weighs a costly error."),
            ("What makes a claim about climate checkable?", "A measurable quantity with a source and a timeframe", ["The author's confidence", "The number of shares", "The length of the article"], "Numbers with a base are checkable."),
        ],
    },
    {
        "key": "economy",
        "language": "en",
        "title": "Economics in plain words",
        "description": "Inflation, interest, trade and the choices behind a price.",
        "sections": [
            (
                "Prices and inflation",
                "A price carries information: how scarce something is, what it costs to make, "
                "what people will pay. Inflation measures the change in a basket of prices over "
                "time, which is why the composition of the basket matters as much as the "
                "figure it produces.",
            ),
            (
                "Saving and borrowing",
                "Interest is the price of using money over time. When it rises, borrowing "
                "costs more and saving earns more, which slows demand — usually on purpose, "
                "which is why a central bank changes it.",
            ),
            (
                "Trade",
                "Countries trade because they differ in what they can produce cheaply. A "
                "tariff changes that calculation by taxing the crossing of a border, which "
                "protects a producer and raises the price for a customer.",
            ),
        ],
        "facts": [
            ("What does inflation measure?", "The change in a basket of prices over time", ["The level of prices", "The total money supply", "The rate of growth"], "The basket decides the result."),
            ("What is interest?", "The price of using money over time", ["A tax on income", "A bank fee", "A share of profit"], "It links today's money to tomorrow's."),
            ("What usually happens when central banks raise rates?", "Borrowing becomes more expensive and demand cools", ["Prices rise faster", "Saving becomes unattractive", "Trade stops"], "It is a tool against inflation."),
            ("What is a tariff?", "A tax on imported goods", ["A subsidy for exports", "A quota on production", "A price ceiling"], "The customer usually pays part of it."),
            ("What is GDP?", "The value produced inside a country in a period", ["The money held by the state", "The total of savings", "The average wage"], "It is a flow, not a stock."),
            ("Why do countries specialise?", "They produce some goods at lower opportunity cost", ["They have more people", "They refuse to trade", "They share a currency"], "Comparative advantage explains the gain."),
            ("What is an opportunity cost?", "The value of what you give up to choose something", ["The price paid at the till", "The tax on a purchase", "The interest on a loan"], "Every choice has one."),
            ("What does a price ceiling usually create?", "Shortages", ["Surpluses", "Lower quality", "Higher supply"], "Demand rises above the capped supply."),
            ("What is a stock and what is a flow?", "A stock is a quantity; a flow is per unit of time", ["They are the same", "A flow is stored", "A stock is spent"], "Debt is a stock, deficit a flow."),
            ("Why is a diversified economy more resilient?", "A shock to one sector hurts less", ["It always grows faster", "It avoids imports", "It needs no tax"], "Concentration amplifies shocks."),
            ("What does a subsidy do?", "Lowers the cost of producing or buying something", ["Raises a price", "Bans a product", "Taxes an import"], "It shifts the cost to the budget."),
            ("What is productivity?", "Output produced per unit of work", ["The number of employees", "The total output", "The price of output"], "It underpins long-run growth."),
            ("What does a currency depreciation change?", "Imports become dearer and exports cheaper", ["Both become dearer", "Nothing changes", "Only savings change"], "It rebalances trade slowly."),
            ("Why is a basket of prices revised?", "Consumption habits change over time", ["Politicians dislike the old one", "Prices stop moving", "It is a legal requirement"], "An obsolete basket measures the past."),
            ("What is the difference between debt and deficit?", "Debt is accumulated; deficit is this year's gap", ["They are synonyms", "Deficit is accumulated", "Both are annual"], "One is a stock, the other a flow."),
        ],
    },
    {
        "key": "languages",
        "language": "en",
        "title": "Learning a language",
        "description": "Sound, vocabulary, grammar and the habits that make a language stick.",
        "sections": [
            (
                "Sound first",
                "A language is a set of contrasts, and each one draws the line between sounds "
                "differently. Hearing the difference before writing it down prevents errors "
                "that are hard to undo later, because the ear decides what the mouth does.",
            ),
            (
                "Words in context",
                "A word learned alone is a definition; the same word in three sentences is a "
                "tool. Frequency lists reward the beginner, because a few hundred words cover "
                "a large share of everyday speech.",
            ),
            (
                "Speaking early",
                "Waiting for fluency delays it. Speaking badly, often, with feedback, is what "
                "builds fluency; the mistakes are the material the correction works on.",
            ),
        ],
        "facts": [
            ("What should a beginner learn first in a new language?", "The sounds that carry meaning", ["Every grammar rule", "Long vocabulary lists", "Poetry"], "The ear guides the mouth."),
            ("Why do frequency lists help beginners?", "A few hundred words cover a large share of speech", ["They are shorter to print", "They are easier to spell", "They avoid grammar"], "Common words recur constantly."),
            ("What makes vocabulary stick?", "Meeting a word in several contexts", ["Writing it ten times", "Reading it once", "Translating it aloud"], "Context gives it hooks."),
            ("What is a cognate?", "A word that resembles one in another language", ["A false friend", "A borrowed grammar rule", "A dialect"], "Resemblance can mislead."),
            ("Why is speaking early useful?", "Mistakes become correctable material", ["It avoids listening", "It replaces reading", "It guarantees fluency"], "Feedback accelerates learning."),
            ("What does spaced repetition optimise?", "The timing of reviews", ["The length of a lesson", "The number of words introduced", "The accent"], "It exploits forgetting."),
            ("What is a false friend?", "A word that looks familiar but means something else", ["A rare synonym", "An archaic form", "A dialect word"], "Spanish 'embarazada' is not embarrassed."),
            ("Why does immersion accelerate learning?", "The language is needed, not studied", ["It removes grammar", "It avoids mistakes", "It is cheaper"], "Necessity drives attention."),
            ("What helps listening comprehension most?", "Hearing the same material at several speeds", ["Reading the transcript once", "Studying phonetics only", "Silent reading"], "Slow first, then natural speed."),
            ("What is grammatical gender?", "A noun class that affects agreement", ["A rule about politeness", "A verb tense", "A writing system"], "It is only loosely tied to meaning."),
            ("Why do learners overgeneralise rules?", "They apply a pattern beyond its domain", ["They are careless", "They forget vocabulary", "They read too little"], "Overgeneralisation shows progress."),
            ("What is the best use of a dictionary in reading?", "Look up words that block meaning, not every word", ["Look up every word", "Never use one", "Only use a bilingual one"], "Flow matters more than completeness."),
            ("What does shadowing practise?", "Speaking immediately after a model, copying rhythm", ["Translating word by word", "Memorising lists", "Writing summaries"], "It joins listening and speaking."),
            ("Why is a little grammar useful?", "It names patterns the learner already half-sees", ["It guarantees correctness", "It replaces practice", "It shortens the vocabulary"], "A frame helps the picture."),
            ("How long does a language take to learn?", "It depends on the pair, the goal and the practice", ["Three months always", "A fixed number of hours", "It cannot be measured"], "Distance between languages matters."),
        ],
    },
    {
        "key": "music",
        "language": "en",
        "title": "How music works",
        "description": "Rhythm, harmony, form and the reasons a melody stays in your head.",
        "sections": [
            (
                "Rhythm",
                "Rhythm is organised time: a pulse, a division of that pulse, and accents that "
                "tell the ear where the group begins. Change the accent and the same notes "
                "become a different dance.",
            ),
            (
                "Harmony",
                "Two notes sound consonant when their frequencies relate simply. Harmony builds "
                "on that relationship, and tension comes from moving away from the simplest "
                "ratios and then returning to them.",
            ),
            (
                "Form and memory",
                "A piece repeats and varies to be remembered. Repetition makes a shape, "
                "variation keeps attention, and the return of the opening is what makes a long "
                "work feel complete.",
            ),
        ],
        "facts": [
            ("What is rhythm in music?", "The organisation of sound in time", ["The pitch of notes", "The loudness of a piece", "The number of instruments"], "Pulse, division and accent."),
            ("What makes two notes consonant?", "Their frequencies relate by a simple ratio", ["They are played loudly", "They share a name", "They are the same octave"], "Octaves and fifths are simple."),
            ("What is a scale?", "An ordered set of notes used in a piece", ["A volume control", "A type of instrument", "A tempo marking"], "Scales shape the mood."),
            ("What does a chord do?", "Sounds several notes together as a unit", ["Sets the tempo", "Marks the beat", "Changes the key"], "Harmony is built from chords."),
            ("What is a tempo?", "The speed of the pulse", ["The loudness", "The key", "The number of beats per bar"], "It is given in beats per minute."),
            ("Why do pieces repeat material?", "Repetition makes a form the listener can follow", ["It is easier to play", "It hides mistakes", "It fills the score"], "Variation keeps attention."),
            ("What is an octave?", "The interval where one frequency is double the other", ["A fifth", "A semitone", "A mode"], "The notes sound alike."),
            ("What does a key signature indicate?", "Which notes belong to the piece by default", ["The volume", "The tempo", "The instrument"], "Accidentals mark exceptions."),
            ("What is syncopation?", "An accent placed off the expected beat", ["A very slow tempo", "A silent bar", "A chord change"], "It drives dance music."),
            ("Why does a melody get stuck in the head?", "Short, repeated, slightly irregular patterns are memorable", ["It is loud", "It uses many notes", "It is fast"], "Simplicity plus one surprise."),
            ("What is a bar?", "A group of beats between two accents", ["A loud passage", "A change of key", "The end of a piece"], "The time signature defines it."),
            ("What does a minor scale often suggest?", "A darker or more melancholic colour", ["A faster tempo", "A louder sound", "A different rhythm"], "The third is lower."),
            ("What is orchestration?", "Deciding which instruments play which part", ["Tuning the orchestra", "Writing the melody", "Setting the tempo"], "It changes the colour of an idea."),
            ("Why is silence part of music?", "It sets off sound and shapes expectation", ["It saves the players' energy", "It marks page turns", "It is required notation"], "The pause carries weight."),
            ("What does practising slowly improve?", "Control and accuracy before speed", ["Only memory", "Only stamina", "Only reading"], "Speed hides imprecision."),
        ],
    },
    {
        "key": "nutrition",
        "language": "en",
        "title": "Food, energy and health",
        "description": "What a label says, what macronutrients do, and how to judge a diet claim.",
        "sections": [
            (
                "Energy balance",
                "Weight changes follow the balance between energy eaten and energy spent, but "
                "both sides are harder to measure than a label suggests: absorption varies, "
                "portions are misjudged, and activity is overestimated.",
            ),
            (
                "Macronutrients",
                "Carbohydrates, fats and proteins provide energy and building material in "
                "different roles. Fibre, though poorly absorbed, feeds the gut and slows the "
                "arrival of sugar in the blood.",
            ),
            (
                "Judging claims",
                "A food claim is usually about one nutrient in one product. What matters is "
                "the whole diet and the pattern over weeks, which is why a single product "
                "rarely transforms anything.",
            ),
        ],
        "facts": [
            ("What does a food label's energy value depend on?", "The portion size it refers to", ["The price", "The packaging", "The brand"], "Always check the reference amount."),
            ("Which nutrient provides the most energy per gram?", "Fat", ["Protein", "Carbohydrate", "Fibre"], "About nine kilocalories per gram."),
            ("What does fibre do?", "Feeds gut bacteria and slows sugar absorption", ["Provides bulk energy", "Replaces protein", "Dissolves fat"], "It is mostly not digested."),
            ("Why is a single food rarely a health solution?", "The whole diet and pattern matter more", ["Foods cancel each other", "Labels are wrong", "Nutrition is unknown"], "Look at the week, not the meal."),
            ("What is a calorie?", "A unit of energy", ["A unit of mass", "A vitamin", "A portion size"], "On labels it means a kilocalorie."),
            ("Why does protein matter after exercise?", "It supplies the material to repair muscle", ["It burns fat directly", "It replaces water", "It speeds digestion"], "Spread across the day."),
            ("What does hydration affect?", "Blood volume and temperature regulation", ["Bone density", "Muscle length", "Eye colour"], "Thirst arrives late."),
            ("Why can portions be misjudged?", "People estimate volume poorly without scales", ["Food contains hidden air", "Plates are always wrong", "Recipes are inaccurate"], "Measuring once is informative."),
            ("What is a balanced diet?", "One supplying energy and nutrients in the right proportions", ["One with equal weights of food", "One without fat", "One with only plants"], "Variety is the practical rule."),
            ("What does a 'light' product usually change?", "One nutrient, often sugar or fat", ["The total energy always", "The vitamin content", "The fibre"], "Read the whole table."),
            ("Why is salt easy to overconsume?", "It is in processed food without tasting salty", ["It is sweet", "It is invisible", "It is added at the table only"], "Bread and cheese contribute a lot."),
            ("What is a micronutrient?", "A vitamin or mineral needed in small amounts", ["A fat", "A sugar", "A protein"], "Small amount, large effect."),
            ("Why do official recommendations change?", "The evidence base improves over time", ["Governments change", "Foods change", "People lie"], "Guidelines are summaries of evidence."),
            ("What is the most reliable way to judge a diet claim?", "Look for the study and the population behind it", ["Trust the packaging", "Ask a friend", "Follow the trend"], "Evidence, then enthusiasm."),
            ("What does cooking at home change?", "Portion control and ingredient knowledge", ["The nutrient value of everything", "The need for vegetables", "The cost of energy"], "It is not a guarantee, but it helps."),
            ("What does 'energy density' describe?", "How much energy a food carries per gram", ["How heavy a portion is", "How sweet a food is", "How long it keeps"], "Vegetables are low, oils are high."),
        ],
    },
]
