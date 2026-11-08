"""Build the demo catalogue from compact, reviewed fact sheets.

The JSON files under ``content/`` are the source of truth at runtime, but writing
a hundred questionnaires by hand invites typos and duplicated questions. This
script keeps one reviewed sheet per theme and expands it into:

* one wiki per theme, with pages cut from the theme's sections;
* three questionnaires per theme, five questions each, drawn without repetition;
* one revision deck per theme, built from the same facts.

Run it from the repository root::

    python -m app.demo.build_content

It only writes into ``app/demo/content`` and is not imported at runtime.
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

# Runtime content lives at <repo>/demo/content (see settings.demo_content_dir).
CONTENT_DIR = Path(__file__).resolve().parents[3] / "demo" / "content"

# --------------------------------------------------------------------------- #
# Fact sheets. One entry per theme: a title, a few sections of prose, and the
# facts the questionnaires and the deck are built from.
# --------------------------------------------------------------------------- #

THEMES: list[dict[str, Any]] = [
    {
        "key": "geography",
        "language": "en",
        "title": "Physical geography",
        "description": "Continents, oceans, climate and the forces that shape the surface of the Earth.",
        "sections": [
            (
                "The oceans",
                "Oceans cover about seventy-one percent of the surface and hold roughly "
                "ninety-seven percent of the water on Earth. The Pacific is the largest and "
                "deepest, followed by the Atlantic, the Indian, the Southern and the Arctic. "
                "The Mariana Trench, in the western Pacific, reaches almost eleven kilometres "
                "below sea level, further down than Everest rises.",
            ),
            (
                "Continents and plates",
                "The crust is broken into plates that drift a few centimetres a year. Where "
                "two plates meet, the result is a mountain range, a deep trench, or a chain of "
                "volcanoes; where they slide past each other, the ground shakes. Africa and "
                "South America fit together because they were once part of the same landmass.",
            ),
            (
                "Climate zones",
                "Sunlight arrives at a slant, which is why the poles are colder than the "
                "equator. Winds and currents move that heat around: the Gulf Stream keeps "
                "north-western Europe mild for its latitude, while the same ocean a few "
                "degrees west carries ice south along Canada's coast.",
            ),
        ],
        "facts": [
            ("Which ocean is the largest and deepest?", "Pacific", ["Atlantic", "Indian", "Arctic"], "It is also the oldest ocean floor."),
            ("What share of Earth's water is held by the oceans?", "About 97%", ["About 71%", "About 50%", "About 30%"], "Rivers and lakes hold less than 1%."),
            ("What is the deepest point of the ocean called?", "The Mariana Trench", ["The Puerto Rico Trench", "The Java Trench", "The Tonga Trench"], "It lies in the western Pacific."),
            ("Roughly how fast do tectonic plates move?", "A few centimetres per year", ["A few metres per year", "A few millimetres per century", "They do not move"], "About as fast as a fingernail grows."),
            ("What forms where two plates pull apart?", "A rift, often filled by a new ocean", ["A mountain range", "A desert", "A glacier"], "The East African Rift is an example."),
            ("Why are the poles colder than the equator?", "Sunlight strikes them at a slant", ["They are further from the Sun", "They have no atmosphere", "They rotate faster"], "The same energy is spread over a wider area."),
            ("Which current keeps north-western Europe mild?", "The Gulf Stream", ["The Humboldt Current", "The Kuroshio Current", "The Benguela Current"], "It carries warm water north-east across the Atlantic."),
            ("What percentage of the Earth's surface is covered by water?", "About 71%", ["About 50%", "About 60%", "About 85%"], "Most of it is salt water."),
            ("Which two continents fit together like puzzle pieces?", "Africa and South America", ["Europe and Asia", "Australia and Antarctica", "Asia and North America"], "They were joined in Pangaea."),
            ("What instrument measures the strength of an earthquake?", "A seismograph", ["A barometer", "An anemometer", "A hygrometer"], "It records ground motion over time."),
            ("What is the boundary where a plate sinks under another called?", "A subduction zone", ["A mid-ocean ridge", "A transform fault", "A hotspot"], "It produces deep trenches and volcanoes."),
            ("Which layer of the Earth is liquid?", "The outer core", ["The inner core", "The crust", "The lower mantle"], "Its movement generates the magnetic field."),
            ("What causes tides?", "The pull of the Moon and the Sun", ["Prevailing winds", "Undersea volcanoes", "The Earth's rotation alone"], "The Moon dominates because it is close."),
            ("What is a rain shadow?", "The dry side of a mountain range", ["A cloud that blocks the Sun", "A forest that stops rain", "A river that dries up in summer"], "Air loses its moisture climbing the windward side."),
            ("Which line divides the Earth into northern and southern halves?", "The equator", ["The prime meridian", "The Tropic of Cancer", "The Arctic Circle"], "It sits at zero degrees latitude."),
        ],
    },
    {
        "key": "history",
        "language": "en",
        "title": "Turning points of history",
        "description": "A short tour of the inventions, cities and decisions that changed how people lived.",
        "sections": [
            (
                "Writing and the first cities",
                "Writing appeared around 3200 BCE in Mesopotamia, first as accounts of grain "
                "and labour, then as law and literature. Cities grew where rivers flooded "
                "predictably, because a surplus of food let some people specialise in "
                "something other than farming.",
            ),
            (
                "Print and the spread of ideas",
                "Movable type in fifteenth-century Europe made copying cheap. A text that "
                "once took months to reproduce could be printed in hundreds of copies in "
                "weeks, and arguments travelled faster than the authorities could answer them.",
            ),
            (
                "Industry and after",
                "Steam power moved production from workshops to factories and drew people "
                "into cities. The same period produced public schooling, sanitation and, "
                "eventually, the idea that knowledge should be available to everyone rather "
                "than kept behind a guild.",
            ),
        ],
        "facts": [
            ("Where did writing first appear, around 3200 BCE?", "Mesopotamia", ["Egypt", "China", "Greece"], "It began as accounting records."),
            ("What made movable type revolutionary in Europe?", "It made copies far cheaper to produce", ["It invented the alphabet", "It allowed colour printing", "It replaced spoken language"], "Printed arguments spread faster than censorship."),
            ("Which invention moved production into factories?", "The steam engine", ["The printing press", "The telegraph", "The compass"], "Steam power no longer depended on a river."),
            ("Why did the first cities grow beside rivers?", "Flooding left fertile soil and a food surplus", ["Rivers made good roads", "Rivers provided stone", "Rivers kept enemies away"], "Surplus food let people specialise."),
            ("What did the printing press make possible for learning?", "Widely shared, identical texts", ["Cheaper paper", "Faster handwriting", "New languages"], "Errors could be corrected once and reprinted."),
            ("Which ancient library is famous for collecting the ancient world's texts?", "The Library of Alexandria", ["The Library of Pergamon", "The Library of Baghdad", "The Bodleian Library"], "Its decline remains debated."),
            ("What was the Silk Road?", "A network of trade routes between Asia and Europe", ["A single paved road", "A sea route to India", "A Roman military road"], "Goods travelled with ideas and technologies."),
            ("Which document limited the power of the English king in 1215?", "Magna Carta", ["The Bill of Rights", "The Treaty of Versailles", "The Code of Hammurabi"], "It established that the king was subject to law."),
            ("What was the Renaissance a revival of?", "Classical learning and art", ["Industrial machinery", "Religious law", "Military tactics"], "It began in the Italian city-states."),
            ("Which empire built the road network later used across Europe?", "The Roman Empire", ["The Ottoman Empire", "The Mongol Empire", "The Byzantine Empire"], "Some routes are still in use."),
            ("What did the telegraph change?", "The speed at which news could travel", ["The cost of paper", "The shape of cities", "The length of the working day"], "Messages no longer needed a messenger."),
            ("Which revolution began in Britain in the eighteenth century?", "The Industrial Revolution", ["The Neolithic Revolution", "The Scientific Revolution", "The Digital Revolution"], "Coal, iron and steam drove it."),
            ("What is an archive?", "A collection of records kept for the future", ["A museum of objects", "A library of novels", "A list of laws"], "Archives are the raw material of history."),
            ("Why do historians compare several sources?", "To test each account against the others", ["To find the longest text", "To choose the oldest paper", "To avoid reading originals"], "A single source carries a single point of view."),
            ("What did public schooling make possible?", "Literacy beyond a small elite", ["Cheaper books", "Faster printing", "Shorter working days"], "Reading spread from the few to the many."),
        ],
    },
    {
        "key": "science",
        "language": "en",
        "title": "Everyday science",
        "description": "Cells, energy, chemical reactions and the physics behind ordinary things.",
        "sections": [
            (
                "Cells and life",
                "A cell is the smallest unit that can be called alive. Bacteria are single "
                "cells; a human body holds tens of trillions, organised into tissues and "
                "organs. Almost all of them carry the same DNA, and what makes a liver cell "
                "different from a skin cell is which parts of that DNA are switched on.",
            ),
            (
                "Energy and heat",
                "Energy is never created or destroyed, only converted. A bulb turns "
                "electricity into light and heat; a muscle turns sugar into movement and "
                "heat. Heat itself moves from warm to cold, which is why a room cools down "
                "rather than the outside warming up.",
            ),
            (
                "Matter and reactions",
                "Atoms combine and separate in reactions, but the atoms themselves survive. "
                "A catalyst speeds a reaction without being consumed, which is how the body "
                "runs thousands of reactions at temperatures far below those of a laboratory.",
            ),
        ],
        "facts": [
            ("What is the smallest unit of life?", "The cell", ["The atom", "The organ", "The tissue"], "Some organisms are a single cell."),
            ("What does DNA carry?", "The instructions for building and running a cell", ["Energy for the cell", "Water for the cell", "Waste from the cell"], "Almost every cell in a body holds the same DNA."),
            ("What happens to energy in any process?", "It is converted, never destroyed", ["It is used up", "It is created", "It disappears"], "The total amount stays constant."),
            ("Which way does heat flow?", "From warmer to colder", ["From colder to warmer", "In both directions equally", "It does not flow"], "A fridge moves heat the other way by doing work."),
            ("What does a catalyst do?", "Speeds a reaction without being consumed", ["Provides energy to a reaction", "Stops a reaction", "Changes the products"], "Enzymes are biological catalysts."),
            ("What is a molecule?", "Two or more atoms bonded together", ["A single atom", "A cell organelle", "A mixture of elements"], "Water is one oxygen and two hydrogen atoms."),
            ("What is photosynthesis for?", "Turning light into chemical energy", ["Releasing energy from sugar", "Copying DNA", "Breaking down waste"], "Plants, algae and some bacteria do it."),
            ("What gas do plants take from the air to grow?", "Carbon dioxide", ["Oxygen", "Nitrogen", "Hydrogen"], "They release oxygen as a by-product."),
            ("What is the pH of a neutral solution?", "7", ["0", "14", "1"], "Below 7 is acidic, above is basic."),
            ("Which force keeps planets in orbit?", "Gravity", ["Magnetism", "Friction", "Buoyancy"], "It weakens with the square of the distance."),
            ("What is the speed of light in a vacuum?", "About 300,000 km/s", ["About 30,000 km/s", "About 3,000 km/s", "About 3,000,000 km/s"], "It is the cosmic speed limit."),
            ("What does a vaccine do?", "Trains the immune system to recognise a pathogen", ["Kills all bacteria in the body", "Replaces antibodies", "Stops the spread of a virus"], "It leaves a memory without the disease."),
            ("What are the three states of matter most people meet daily?", "Solid, liquid and gas", ["Solid, plasma and gas", "Liquid, plasma and solid", "Gas, plasma and liquid"], "Plasma is common in stars."),
            ("What is erosion?", "The transport of material by wind, water or ice", ["The melting of rock", "The growth of crystals", "The freezing of soil"], "It shapes valleys and coastlines."),
            ("Why does ice float on water?", "It is less dense than liquid water", ["It is colder", "It contains air", "It is lighter than air"], "Water expands when it freezes."),
        ],
    },
    {
        "key": "technology",
        "language": "en",
        "title": "How the web works",
        "description": "Networks, browsers, servers and the principles that keep the web open.",
        "sections": [
            (
                "Names and addresses",
                "Computers find each other by number, but people remember names. The Domain "
                "Name System translates one into the other, in a hierarchy that starts at the "
                "root and descends to a single machine. Caching copies the answer along the "
                "way so the question is not asked again.",
            ),
            (
                "Requests and responses",
                "A browser sends a request with a method, a path and headers; the server "
                "answers with a status code, headers and a body. HTTPS wraps that exchange in "
                "TLS, which proves the server's identity and encrypts what passes.",
            ),
            (
                "An open web",
                "The web is built on specifications anyone may implement, which is why one "
                "page works in every browser. The same principle applies to data: an open "
                "format lets a reader move their notes, quizzes and pages to another tool "
                "without asking permission.",
            ),
        ],
        "facts": [
            ("What does DNS do?", "Translates a domain name into an IP address", ["Encrypts web traffic", "Compresses images", "Stores passwords"], "It is a distributed hierarchy."),
            ("What does HTTPS add to HTTP?", "Encryption and proof of the server's identity", ["Faster downloads", "Smaller pages", "Better caching"], "It runs over TLS."),
            ("What does HTTP status 404 mean?", "The resource does not exist", ["The server failed", "Access is denied", "The request was too large"], "410 means it existed and is gone."),
            ("What is a cookie used for?", "Keeping state between requests", ["Encrypting the connection", "Compressing files", "Resolving names"], "HTTP itself is stateless."),
            ("What is the role of a web browser?", "Requesting, rendering and running pages", ["Hosting websites", "Assigning IP addresses", "Storing databases"], "It also enforces security policies."),
            ("Why is an open web standard important?", "Anyone can implement it, so no vendor controls access", ["It is cheaper to write", "It loads faster", "It looks better"], "Interoperability comes from shared specifications."),
            ("What is an API?", "A defined way for programs to exchange data", ["A programming language", "A database engine", "A browser extension"], "It is a contract, not a UI."),
            ("What does a CDN do?", "Serves files from a location near the visitor", ["Encrypts passwords", "Indexes pages", "Backs up databases"], "It reduces latency."),
            ("What is the difference between a domain and a URL?", "A domain names a host; a URL locates a resource on it", ["They are the same", "A URL is shorter", "A domain includes a path"], "The URL adds scheme, path and query."),
            ("What does JSON represent?", "Structured data as nested keys and values", ["A compressed archive", "An image format", "A stylesheet language"], "It is readable by humans and machines."),
            ("Why does a password need to be hashed, not stored?", "So a stolen database does not reveal the passwords", ["To make logins faster", "To save space", "To allow recovery"], "Hashing is one-way by design."),
            ("What is a content delivery cache?", "A stored copy of a response, reused until it changes", ["A backup of the database", "A list of blocked sites", "A search index"], "Validation avoids serving stale data."),
            ("What does an open data format allow?", "Moving your content to another tool", ["A faster website", "Smaller images", "Cheaper hosting"], "It prevents vendor lock-in."),
            ("What is a server in the client-server model?", "A program that answers requests", ["The user's browser", "A network cable", "A domain name"], "One server can answer thousands of clients."),
            ("Why do sites publish an API alongside their interface?", "So third-party tools can build on the same data", ["To make pages smaller", "To hide the interface", "To save bandwidth"], "The interface is one client among several."),
        ],
    },
    {
        "key": "ai",
        "language": "en",
        "title": "How language models work",
        "description": "Tokens, training, prompting and the limits of a model that predicts text.",
        "sections": [
            (
                "Tokens and prediction",
                "A language model reads text cut into tokens and estimates what comes next. "
                "Everything it appears to reason about is expressed through that single "
                "operation, repeated one token at a time, with the previous output feeding "
                "the next step.",
            ),
            (
                "Training and limits",
                "Training adjusts billions of weights to make the next token more likely on "
                "a large body of text. What the model learns is a statistical picture of "
                "language, not a database of verified facts, which is why a confident answer "
                "can still be wrong.",
            ),
            (
                "Working with a model",
                "Giving the model the relevant document, a clear task and worked examples "
                "usually matters more than any clever wording. For anything that must be "
                "true, the output has to be checked against a source that did not come from "
                "the model.",
            ),
        ],
        "facts": [
            ("What is a token in a language model?", "A piece of text, shorter than a word on average", ["A whole sentence", "A single character always", "A file"], "Rare words are split into several tokens."),
            ("What does a language model actually predict?", "The next token", ["The meaning of a sentence", "The author's intent", "The factual truth"], "Everything else emerges from that."),
            ("What is a hallucination?", "A confident answer that is not supported by facts", ["A slow response", "A refusal to answer", "A formatting error"], "It follows from predicting plausible text."),
            ("What does the context window limit?", "How much text the model can consider at once", ["How fast it answers", "How many users can connect", "How long it trains"], "Older turns fall out of it."),
            ("What is a prompt?", "The instruction and context given to a model", ["The model's weights", "A cached response", "The training corpus"], "Clarity beats cleverness."),
            ("Why does giving a source document help?", "It grounds the answer in text the model can quote", ["It makes the model faster", "It reduces the token count", "It retrains the model"], "Retrieval reduces invented facts."),
            ("What is fine-tuning?", "Further training on a narrower set of examples", ["Compressing the model", "Caching answers", "Splitting input into tokens"], "It shapes style and task behaviour."),
            ("What does temperature control?", "How random the next-token choice is", ["How long the answer is", "How fast it runs", "How much it costs"], "Low temperature is more deterministic."),
            ("What is an embedding?", "A vector that places a text by its meaning", ["A compressed image", "A type of prompt", "A training dataset"], "Similar meanings lie close together."),
            ("Why must a model's output be verified?", "It optimises for plausibility, not truth", ["It cannot read sources", "It forgets its training", "It refuses to cite"], "Check against a source outside the model."),
            ("What is retrieval-augmented generation?", "Feeding relevant documents into the prompt before answering", ["Training on new data overnight", "Compressing a model", "Translating responses"], "It grounds answers in a corpus."),
            ("What is a system prompt?", "Standing instructions that frame the whole conversation", ["The user's first question", "A list of banned words", "The model's architecture"], "It sets role and constraints."),
            ("Why do two identical prompts sometimes give different answers?", "Sampling is probabilistic", ["The model was retrained", "The server lost data", "Tokens are cached"], "Temperature above zero allows variation."),
            ("What does 'open weights' mean for a model?", "The parameters can be downloaded and run locally", ["The training data is public", "The model is free of errors", "It has no licence"], "It allows self-hosting."),
            ("What is the main cost of a long prompt?", "More tokens to process on every turn", ["Slower model download", "A larger context window", "Fewer possible answers"], "Relevant context beats a large context."),
        ],
    },
    {
        "key": "sport",
        "language": "en",
        "title": "Sport and training",
        "description": "Energy systems, recovery and the habits that make training stick.",
        "sections": [
            (
                "Energy for effort",
                "A short sprint runs on stored energy that lasts seconds; a longer effort "
                "burns glycogen and then fat, with oxygen increasingly involved. Training "
                "adapts each system to the demand placed on it, which is why a good distance "
                "runner is not automatically a good sprinter.",
            ),
            (
                "Recovery",
                "Adaptation happens between sessions, not during them. Sleep, food and an "
                "easy day are part of the programme: training hard without recovering "
                "produces fatigue rather than progress.",
            ),
            (
                "Practice that transfers",
                "Skill improves fastest with focused repetitions, feedback and variation. "
                "Repeating an easy version of a movement builds confidence, not competence; "
                "the useful repetitions are the ones that are slightly too hard.",
            ),
        ],
        "facts": [
            ("Which system powers a short, maximal sprint?", "Stored energy used without oxygen", ["Fat oxidation", "The aerobic system", "Digestion"], "It lasts a few seconds."),
            ("When does the body adapt to training?", "During recovery between sessions", ["During the hardest set", "During warm-up", "While stretching only"], "Fatigue is the stimulus, rest is the adaptation."),
            ("What does aerobic training improve?", "The ability to use oxygen over long efforts", ["Maximum sprint speed", "Grip strength", "Flexibility only"], "It builds the heart and the capillary network."),
            ("Why is sleep part of a training plan?", "It is when most recovery happens", ["It burns extra calories", "It replaces warm-up", "It increases flexibility"], "Short sleep blunts adaptation."),
            ("What is progressive overload?", "Gradually increasing the demand of training", ["Training until exhaustion", "Repeating the same session", "Changing sport weekly"], "Small increments are sustainable."),
            ("What does a warm-up prepare?", "Muscles, joints and the cardiovascular system for effort", ["Only the mind", "Only the lungs", "Only the muscles"], "It also rehearses the movement."),
            ("Why do varied repetitions improve a skill?", "They build a general pattern, not one fixed motion", ["They are easier", "They need less sleep", "They avoid feedback"], "Too much variation prevents refinement."),
            ("What is carbohydrate loading for?", "Filling glycogen stores before a long effort", ["Building muscle mass", "Speeding recovery after sprints", "Reducing hydration"], "It matters for endurance events."),
            ("What is a common sign of overtraining?", "Resting heart rate rising and performance falling", ["Deeper sleep", "Higher motivation", "Faster recovery"], "It needs rest, not more work."),
            ("What does hydration affect first?", "Blood volume and the ability to regulate heat", ["Muscle size", "Bone density", "Reflex speed"], "Thirst arrives late."),
            ("Why does a coach give feedback immediately?", "The correction is easier to apply while the movement is fresh", ["It saves the coach time", "It shortens the session", "It avoids video"], "Delayed feedback still helps, but less."),
            ("What is the value of an easy session?", "It adds volume without adding much fatigue", ["It replaces hard work", "It builds maximum strength", "It shortens recovery"], "Most training should be easy."),
            ("Which nutrient repairs muscle after training?", "Protein", ["Fat", "Fibre", "Sugar"], "Spread across the day, not only after training."),
            ("Why is specificity important in training?", "You improve what you practise", ["All sports use the same energy", "Variety prevents progress", "Strength always transfers"], "Adaptation follows the demand."),
            ("What is a taper?", "Reducing training before a competition", ["Increasing volume sharply", "Changing sports", "Stopping all activity for months"], "It lets fatigue drop while fitness stays."),
        ],
    },
    {
        "key": "arts",
        "language": "en",
        "title": "Reading a work of art",
        "description": "Composition, colour, context and the questions that open a painting or a novel.",
        "sections": [
            (
                "Composition",
                "A picture guides the eye before it says anything. Lines, contrasts and "
                "empty space decide where the eye enters and where it rests, and a painter "
                "arranges those on purpose, whether the result looks planned or casual.",
            ),
            (
                "Colour and light",
                "Colour carries temperature and mood as much as description. Warm tones "
                "advance; cool ones recede. Light tells the viewer where to look and, in "
                "many paintings, what the artist wanted the scene to mean.",
            ),
            (
                "Context",
                "A work is also an answer to the world it was made in: who paid for it, who "
                "could see it, what was fashionable, what was forbidden. Reading a work "
                "closely and knowing its moment are complementary, not rival, exercises.",
            ),
        ],
        "facts": [
            ("What does composition describe in a picture?", "How the elements are arranged in the frame", ["The price of the work", "The artist's biography", "The size of the canvas"], "It directs the viewer's eye."),
            ("Which colours tend to advance towards the viewer?", "Warm colours", ["Cool colours", "Neutral greys", "Black only"], "Cool tones recede."),
            ("What is chiaroscuro?", "Strong contrast between light and dark", ["A type of frame", "A painting technique using wax", "A style of poetry"], "Caravaggio used it dramatically."),
            ("Why does context matter for a work of art?", "It explains what the work answered to", ["It proves the work is good", "It fixes its price", "It replaces close looking"], "Patronage and censorship shape what is made."),
            ("What is a vanishing point?", "Where parallel lines appear to meet in perspective", ["The centre of a canvas", "The brightest area", "The signature of the artist"], "It creates depth on a flat surface."),
            ("What does a novel's narrator control?", "What the reader can know, and when", ["The length of the book", "The price of the edition", "The cover design"], "An unreliable narrator makes this visible."),
            ("What is the difference between story and plot?", "Story is the events; plot is their arrangement", ["They are identical", "Plot is shorter", "Story is only dialogue"], "Order changes meaning."),
            ("What does negative space do?", "Gives the subject room and emphasis", ["Hides the background", "Fills the frame", "Marks the frame"], "Silence works the same way in music."),
            ("Why do museums group works by period?", "Shared constraints and conventions become visible", ["It is cheaper to hang", "It protects the frames", "It follows the law"], "It shows what changed, and when."),
            ("What is a motif in literature?", "A recurring element that carries meaning", ["The main character", "The final sentence", "The book's title"], "Repetition builds significance."),
            ("What does an artist's use of scale emphasise?", "Importance, power or vulnerability", ["The cost of materials", "The speed of painting", "The frame size"], "A huge figure dominates a room."),
            ("Why is a first reading rarely the last?", "Meaning changes with what the reader brings", ["Books decay", "Editions differ", "Authors rewrite endings"], "Re-reading reveals structure."),
            ("What is a still life usually about?", "Ordinary objects arranged for study", ["Historical battles", "Religious scenes", "Landscapes"], "It often carries a moral about time."),
            ("What makes a translation an interpretation?", "Every choice privileges some meanings over others", ["It copies the original exactly", "It shortens the text", "It changes the author"], "Two translations can differ widely."),
            ("What question helps most when looking at a work?", "What is the artist asking me to notice?", ["How much is it worth?", "Who owned it?", "Is it famous?"], "Attention is the beginning of reading."),
        ],
    },
    {
        "key": "health",
        "language": "en",
        "title": "Health literacy",
        "description": "How to read a study, judge a risk and make sense of a health claim.",
        "sections": [
            (
                "Reading a study",
                "A result is a comparison: between groups, over time, against a baseline. "
                "How many people took part, how they were selected, and what the comparison "
                "actually measured decide whether a finding travels beyond that sample.",
            ),
            (
                "Risk and numbers",
                "Absolute risk says how many people are affected; relative risk says how "
                "much the rate changes. A doubling sounds dramatic and can still mean two "
                "cases instead of one in ten thousand, so both numbers matter.",
            ),
            (
                "Claims and evidence",
                "A single study is a data point, not a conclusion. Reviews that pool several "
                "studies carry more weight, and the strongest claims survive attempts to "
                "replicate them.",
            ),
        ],
        "facts": [
            ("What is absolute risk?", "How many people in a group are affected", ["The percentage change between groups", "The cost of treatment", "The survival time"], "It is the number that matters to a patient."),
            ("What is relative risk?", "How much a rate changes between groups", ["The number of cases", "The number of participants", "The duration of a study"], "A doubling of a small number stays small."),
            ("What makes a randomised trial stronger?", "Participants are assigned to groups by chance", ["It is published quickly", "It uses more statistics", "It is funded privately"], "Chance assignment limits bias."),
            ("What is a placebo effect?", "An improvement caused by expectation, not the treatment", ["A side effect of a drug", "A dosing error", "A statistical mistake"], "Blinding is used to control for it."),
            ("Why do reviews pool several studies?", "A larger base gives a more stable estimate", ["They are quicker to write", "They avoid statistics", "They replace trials"], "They also show disagreement."),
            ("What does 'statistically significant' mean?", "The result is unlikely to be chance alone", ["The effect is large", "The result is important", "The study is perfect"], "Significance is not clinical importance."),
            ("Why is a control group needed?", "To show what would have happened without the treatment", ["To increase the sample", "To speed the trial", "To reduce costs"], "Comparison is what creates evidence."),
            ("What is a confounding factor?", "Something else that differs between groups and explains the result", ["A deliberate error", "A missing questionnaire", "A legal requirement"], "Randomisation spreads such factors out."),
            ("Why can a headline about risk mislead?", "It reports relative change without the baseline", ["It is written by journalists", "It omits the authors", "It is too long"], "Ask how many people, out of how many."),
            ("What does prevalence describe?", "How many people have a condition at a time", ["Speed of contagion", "Severity of symptoms", "Cost of care"], "Incidence counts new cases."),
            ("Why are replicas of a study valuable?", "They test whether the first result holds", ["They are cheaper to run", "They replace peer review", "They reduce the sample"], "One result is not a rule."),
            ("What does informed consent require?", "Understanding the risks and agreeing freely", ["Paying for treatment", "Signing a contract", "Following a doctor's order"], "It is a conversation, not a signature."),
            ("What is a symptom?", "Something the patient experiences", ["A measurement taken by a machine", "A diagnosis", "A treatment"], "A sign is what an observer finds."),
            ("Why is a screening test's false-positive rate important?", "It decides how many healthy people are alarmed", ["It sets the price", "It shortens the wait", "It replaces diagnosis"], "Rare conditions amplify false positives."),
            ("What is the first question to ask about a health claim?", "How strong is the evidence behind it?", ["Who said it?", "Is it new?", "Is it popular?"], "Evidence beats confidence."),
        ],
    },
]


def _all_themes() -> list[dict[str, Any]]:
    from .content_themes_extra import EXTRA_THEMES

    return THEMES + EXTRA_THEMES


def _wiki_entry(theme: dict[str, Any]) -> dict[str, Any]:
    pages = []
    for index, (title, body) in enumerate(theme["sections"], start=1):
        slug = title.lower().replace(" ", "-").replace(",", "")
        pages.append(
            {
                "slug": slug,
                "title": title,
                "markdown": f"# {title}\n\n{body}\n\n"
                f"_Part {index} of the {theme['title'].lower()} guide._\n",
                "tags": [theme["key"]],
            }
        )
    pages.append(
        {
            "slug": "key-facts",
            "title": "Key facts",
            "markdown": "# Key facts\n\n"
            + "\n".join(f"- **{question}** {answer}" for question, answer, _, _ in theme["facts"])
            + "\n",
            "tags": [theme["key"], "revision"],
            "parent": pages[0]["slug"],
        }
    )
    return {
        "slug": theme["key"],
        "title": theme["title"],
        "description": theme["description"],
        "language": theme["language"],
        "pages": pages,
    }


def _quiz_entries(theme: dict[str, Any], per_quiz: int = 3, quizzes: int = 5) -> list[dict[str, Any]]:
    facts = theme["facts"][:]
    random.Random(theme["key"]).shuffle(facts)
    entries = []
    total = min(len(facts), per_quiz * quizzes)
    for index in range(0, total, per_quiz):
        chunk = facts[index : index + per_quiz]
        if len(chunk) < per_quiz:
            break
        entries.append(
            {
                "title": f"{theme['title']} — quiz {index // per_quiz + 1}",
                "description": f"Five questions drawn from the {theme['title'].lower()} guide.",
                "mode": "qcm",
                "default_language": theme["language"],
                "wrong_answer_policy": "zero",
                "questions": [
                    {
                        "text_html": question,
                        "time_limit_seconds": 30,
                        "options": [
                            {"text": answer, "is_correct": True},
                            *[{"text": wrong, "is_correct": False} for wrong in wrongs],
                        ],
                    }
                    for question, answer, wrongs, _ in chunk
                ],
            }
        )
    return entries


def _deck_entry(theme: dict[str, Any]) -> dict[str, Any]:
    cards = [
        {"front": question, "back": f"{answer}\n\n{note}"}
        for question, answer, _, note in theme["facts"][:10]
    ]
    return {
        "title": f"{theme['title']} — revision cards",
        "description": f"Ten cards to revise the {theme['title'].lower()} guide.",
        "aspect": "2:3",
        "cards": cards,
    }


def _adventure_entry() -> dict[str, Any]:
    """One short story, in the shape the adventure editor writes."""
    return {
        "title": "The library at the end of the line",
        "description": "A short branching story: a night train, a station that is not on the map, and a library that should not be there.",
        "mode": "adventure",
        "wrong_answer_policy": "zero",
        "default_language": "en",
        "timer_mode": "none",
        "questions": [],
        "adventure": {
            "start": "platform",
            "death_text_html": "<p>The lamp goes out and the shelves close over the platform. The train leaves without you.</p>",
            "victory_text_html": "<p>You write one line, and the station lets you go. The book is in your bag when you wake.</p>",
            "attributes": [
                {
                    "key": "resolve",
                    "label": "Resolve",
                    "initial_value": 3,
                    "min_value": 0,
                    "max_value": 6,
                    "death_at_or_below": 0,
                }
            ],
            "nodes": [
                {
                    "key": "platform",
                    "kind": "question",
                    "text_html": "<p>The train stops at a station that is not on the map. The doors open on a platform lit by a single lamp, and beyond it, a library.</p>",
                    "pos_x": 0,
                    "pos_y": 0,
                    "choices": [
                        {"key": "step", "text": "Step onto the platform", "target": "hall"},
                        {
                            "key": "stay",
                            "text": "Stay in your seat",
                            "target": "gone",
                            "effects": [{"attribute": "resolve", "delta": -2}],
                        },
                    ],
                },
                {
                    "key": "hall",
                    "kind": "question",
                    "text_html": "<p>The shelves run further than the building should allow. A librarian looks up: 'You are early. The book you need is not written yet.'</p>",
                    "pos_x": 240,
                    "pos_y": 0,
                    "choices": [
                        {"key": "about", "text": "Ask what the book is about", "target": "pen"},
                        {
                            "key": "leave",
                            "text": "Ask how to leave",
                            "target": "trees",
                            "effects": [{"attribute": "resolve", "delta": -1}],
                        },
                    ],
                },
                {
                    "key": "pen",
                    "kind": "question",
                    "text_html": "<p>'It is about a reader who arrives too early and writes the missing pages,' she says, and hands you a pen.</p>",
                    "pos_x": 480,
                    "pos_y": 0,
                    "choices": [
                        {"key": "write", "text": "Write", "target": "done"},
                        {
                            "key": "refuse",
                            "text": "Refuse the pen",
                            "target": "gone",
                            "effects": [{"attribute": "resolve", "delta": -3}],
                        },
                    ],
                },
                {
                    "key": "gone",
                    "kind": "ending",
                    "text_html": "<p>The doors close. The train moves on, and the station is gone. The timetable lists a stop that never was.</p>",
                    "outcomes": [
                        {"kind": "default", "text_html": "<p>The doors close. The train moves on, and the station is gone. The timetable lists a stop that never was.</p>", "priority": 0}
                    ],
                    "pos_x": 720,
                    "pos_y": 120,
                    "choices": [],
                },
                {
                    "key": "trees",
                    "kind": "ending",
                    "text_html": "<p>She points to the far door. You walk until the shelves become trees, and the trees become the edge of the town you left that morning.</p>",
                    "outcomes": [
                        {"kind": "default", "text_html": "<p>She points to the far door. You walk until the shelves become trees, and the trees become the edge of the town you left that morning.</p>", "priority": 0}
                    ],
                    "pos_x": 720,
                    "pos_y": -120,
                    "choices": [],
                },
                {
                    "key": "done",
                    "kind": "ending",
                    "text_html": "<p>You write one line: 'The train stops at a station that is not on the map.' The lamp goes out, and you are in your seat again.</p>",
                    "outcomes": [
                        {"kind": "default", "text_html": "<p>You write one line: 'The train stops at a station that is not on the map.' The lamp goes out, and you are in your seat again.</p>", "priority": 0}
                    ],
                    "pos_x": 720,
                    "pos_y": 0,
                    "choices": [],
                },
            ],
        },
    }


def build() -> dict[str, int]:
    CONTENT_DIR.mkdir(parents=True, exist_ok=True)
    themes = _all_themes()
    wikis = [_wiki_entry(theme) for theme in themes]
    quizzes: list[dict[str, Any]] = []
    decks: list[dict[str, Any]] = []
    for theme in themes:
        quizzes.extend(_quiz_entries(theme))
        decks.append(_deck_entry(theme))

    (CONTENT_DIR / "wikis-themes.json").write_text(
        json.dumps({"kind": "wikis", "items": wikis}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (CONTENT_DIR / "quizzes-themes.json").write_text(
        json.dumps({"kind": "quizzes", "items": quizzes}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (CONTENT_DIR / "decks-themes.json").write_text(
        json.dumps({"kind": "decks", "items": decks}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    # Short method guides and the interleaved revision sets.
    from .content_themes_bonus import MINI_WIKIS, mixed_quizzes

    (CONTENT_DIR / "wikis-methods.json").write_text(
        json.dumps({"kind": "wikis", "items": MINI_WIKIS}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    all_facts = [fact for theme in themes for fact in theme["facts"]]
    extra_quizzes = mixed_quizzes(all_facts)
    (CONTENT_DIR / "quizzes-mixed.json").write_text(
        json.dumps({"kind": "quizzes", "items": extra_quizzes}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    (CONTENT_DIR / "adventures-themes.json").write_text(
        json.dumps({"kind": "adventures", "items": [_adventure_entry()]}, indent=2, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    return {
        "wikis": len(wikis) + len(MINI_WIKIS),
        "quizzes": len(quizzes) + len(extra_quizzes),
        "decks": len(decks),
        "adventures": 1,
    }


if __name__ == "__main__":  # pragma: no cover - authoring tool
    print(build())
