// =====================================================================
// Faunistics quiz: vocab-only
// - Species-level quiz
// - Genus-level quiz
// - Family-level quiz
// Images & attribution are pre-baked in the vocab JSON (exampleObservation).
// =====================================================================

// ---------------- CONFIG ----------------------------------------------
const CONFIG = {
  QUESTIONS_COUNT: 10,
  OPTIONS_PER_QUESTION: 4,

  // Vocab files (species-level), one per broad group
  VOCAB_FILES: {
    insects: "data/insects_vocab_sweden.json",
    plants: "data/plants_vocab_sweden.json",
    mosses: "data/mosses_vocab_sweden.json",
    lichens: "data/lichens_vocab_sweden.json",
    mammals: "data/mammals_vocab_sweden.json",
    birds: "data/birds_vocab_sweden.json",
    fungi: "data/fungi_vocab_sweden.json",
    spiders: "data/spiders_vocab_sweden.json",
  },
};

// ---------------- STATE -----------------------------------------------
let vocabByGroup = {};        // { groupKey: [speciesEntry, ...] }
let genusVocabByGroup = {};  // { groupKey: [ { genusName, swedishName, representative }, ... ] }
let familyVocabByGroup = {}; // { groupKey: [ { familyName, swedishName, representative }, ... ] }

let quizQuestions = [];      // [{ correct, options }]
let currentIndex = 0;
let score = 0;
let currentLevel = "species"; // "species" | "genus" | "family"

// ---------------- DOM ELEMENTS ----------------------------------------
const statusEl = document.getElementById("status");
const controlsEl = document.getElementById("controls");
const progressEl = document.getElementById("progress");
const scoreEl = document.getElementById("score");
const questionContainerEl = document.getElementById("question-container");
const photoEl = document.getElementById("photo");
const imageWrapperEl = document.getElementById("image-wrapper");
const answersEl = document.getElementById("answers");
const attributionEl = document.getElementById("attribution");
const nextBtn = document.getElementById("next-btn");
const levelSelectEl = document.getElementById("level-select");

// ---------------- HELPERS ---------------------------------------------

function shuffleArray(array) {
  const arr = array.slice();
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [arr[i], arr[j]] = [arr[j], arr[i]];
  }
  return arr;
}

function pickRandomSubset(array, n) {
  if (array.length <= n) return array.slice();
  return shuffleArray(array).slice(0, n);
}

// generic label helper (works for species/genus/family)
function formatLabel(scientificName, swedishName) {
  const sci = `<i>${scientificName}</i>`;
  return swedishName ? `${sci} (${swedishName})` : sci;
}

function italicizeSci(name) {
  if (!name) return "";
  return `<i>${name}</i>`;
}

// ---------------- LOAD VOCAB ------------------------------------------

async function loadVocab() {
  const entries = Object.entries(CONFIG.VOCAB_FILES);
  const result = {};

  for (const [groupKey, path] of entries) {
    try {
      const res = await fetch(path);
      if (!res.ok) {
        console.warn(
          `Failed to load vocab for ${groupKey} from ${path}: ${res.status}`
        );
        result[groupKey] = [];
        continue;
      }
      const data = await res.json();
      const list = Array.isArray(data) ? data : [];

      // Keep only entries that actually have an exampleObservation with photoUrl
      const filtered = list.filter(
        (e) =>
          e.exampleObservation &&
          e.exampleObservation.photoUrl &&
          e.exampleObservation.obsId
      );
      result[groupKey] = filtered;
      console.log(
        `Loaded ${list.length} species for group "${groupKey}", ` +
          `${filtered.length} with exampleObservation`
      );
    } catch (err) {
      console.warn(`Error loading vocab for ${groupKey} from ${path}`, err);
      result[groupKey] = [];
    }
  }

  vocabByGroup = result;
}

// Build genus-level derived vocab from species vocab
function buildGenusVocabFromSpecies() {
  const result = {};

  for (const [groupKey, speciesList] of Object.entries(vocabByGroup)) {
    const genusMap = new Map(); // genusName -> { genusName, swedishName, representative }

    for (const sp of speciesList) {
      const g = sp.genusName;
      if (!g) continue;

      if (!genusMap.has(g)) {
        genusMap.set(g, {
          genusName: g,
          swedishName: sp.swedishName || null, // borrow first species' Swedish name as hint
          representative: sp,                  // store species entry as representative for photos
        });
      }
    }

    const genera = Array.from(genusMap.values());
    result[groupKey] = genera;
    console.log(`Built ${genera.length} genera for group "${groupKey}"`);
  }

  genusVocabByGroup = result;
}
function buildFamilyVocabFromSpecies() {
  const result = {};

  for (const [groupKey, speciesList] of Object.entries(vocabByGroup)) {
    const familyMap = new Map(); // familyName -> { ... }

    for (const sp of speciesList) {
      const fam = sp.familyName;
      if (!fam) continue;

      const hasFamilySwe = !!sp.familySwedishName;

      const familySwe =
        sp.familySwedishName || sp.swedishName || null;

      if (!familyMap.has(fam)) {
        familyMap.set(fam, {
          familyName: fam,                  // Latin
          swedishName: familySwe,           // Either Swedish family or species name
          representative: sp,
          useExampleSpeciesName: !hasFamilySwe, // <---- NEW FLAG
        });
      }
    }

    const families = Array.from(familyMap.values());
    result[groupKey] = families;
    console.log(`Built ${families.length} families for group "${groupKey}"`);
  }

  familyVocabByGroup = result;
}



// ---------------- BUILD QUIZ: SPECIES LEVEL ---------------------------

async function buildSpeciesQuizQuestionsFromVocab() {
  const neededDistractors = CONFIG.OPTIONS_PER_QUESTION - 1;
  const questions = [];

  const availableGroups = Object.entries(vocabByGroup).filter(
    ([, list]) => list && list.length > neededDistractors
  );

  console.log(
    "Available groups for species quiz:",
    availableGroups.map(([k, list]) => [k, list.length])
  );

  if (!availableGroups.length) {
    console.warn("No vocab groups with enough species to build questions.");
    return [];
  }

  let attempts = 0;
  const MAX_ATTEMPTS = 200;

  while (
    questions.length < CONFIG.QUESTIONS_COUNT &&
    attempts < MAX_ATTEMPTS
  ) {
    attempts++;

    const [groupKey, list] =
      availableGroups[Math.floor(Math.random() * availableGroups.length)];
    if (!list || list.length <= neededDistractors) continue;

    const correctEntry = list[Math.floor(Math.random() * list.length)];
    const ex = correctEntry.exampleObservation;
    if (!ex || !ex.photoUrl) {
      console.warn(
        "No exampleObservation for",
        correctEntry.scientificName,
        "– skipping."
      );
      continue;
    }

    const pool = list.filter((s) => s.taxonId !== correctEntry.taxonId);
    if (pool.length < neededDistractors) continue;

    const distractorEntries = pickRandomSubset(pool, neededDistractors);

    const options = [
      {
        key: String(correctEntry.taxonId), // species: key = taxonId
        labelSci: correctEntry.scientificName,
        labelSwe: correctEntry.swedishName,
      },
      ...distractorEntries.map((d) => ({
        key: String(d.taxonId),
        labelSci: d.scientificName,
        labelSwe: d.swedishName,
      })),
    ];

    questions.push({
      correct: {
        answerKey: String(correctEntry.taxonId),
        labelSci: correctEntry.scientificName,
        labelSwe: correctEntry.swedishName,

        obsId: ex.obsId,
        photoUrl: ex.photoUrl,
        observer: ex.observer || "okänd",
        licenseCode: ex.licenseCode || null,
        obsUrl: ex.obsUrl || "#",
        groupKey,
      },
      options: shuffleArray(options),
    });
  }

  console.log(
    `Species quiz: built ${questions.length} questions after ${attempts} attempts`
  );
  return questions;
}

// ---------------- BUILD QUIZ: GENUS LEVEL -----------------------------

async function buildGenusQuizQuestionsFromVocab() {
  const neededDistractors = CONFIG.OPTIONS_PER_QUESTION - 1;
  const questions = [];

  const availableGroups = Object.entries(genusVocabByGroup).filter(
    ([, list]) => list && list.length > neededDistractors
  );

  console.log(
    "Available groups for genus quiz:",
    availableGroups.map(([k, list]) => [k, list.length])
  );

  if (!availableGroups.length) {
    console.warn("No groups with enough genera to build genus-level questions.");
    return [];
  }

  let attempts = 0;
  const MAX_ATTEMPTS = 200;

  while (
    questions.length < CONFIG.QUESTIONS_COUNT &&
    attempts < MAX_ATTEMPTS
  ) {
    attempts++;

    const [groupKey, genusList] =
      availableGroups[Math.floor(Math.random() * availableGroups.length)];
    if (!genusList || genusList.length <= neededDistractors) continue;

    const correctGenus =
      genusList[Math.floor(Math.random() * genusList.length)];
    const repSpecies = correctGenus.representative;
    const ex = repSpecies.exampleObservation;
    if (!ex || !ex.photoUrl) {
      console.warn(
        "No exampleObservation for representative of genus",
        correctGenus.genusName,
        "– skipping."
      );
      continue;
    }

    const pool = genusList.filter(
      (g) => g.genusName !== correctGenus.genusName
    );
    if (pool.length < neededDistractors) continue;

    const distractorGenera = pickRandomSubset(pool, neededDistractors);

    const options = [
      {
        key: correctGenus.genusName, // genus: key = genusName
        labelSci: correctGenus.genusName,
        labelSwe: null,
      },
      ...distractorGenera.map((g) => ({
        key: g.genusName,
        labelSci: g.genusName,
        labelSwe: null,
      })),
    ];

    questions.push({
      correct: {
        answerKey: correctGenus.genusName,
        labelSci: correctGenus.genusName,
        labelSwe: correctGenus.swedishName,

        obsId: ex.obsId,
        photoUrl: ex.photoUrl,
        observer: ex.observer || "okänd",
        licenseCode: ex.licenseCode || null,
        obsUrl: ex.obsUrl || "#",
        groupKey,
      },
      options: shuffleArray(options),
    });
  }

  console.log(
    `Genus quiz: built ${questions.length} questions after ${attempts} attempts`
  );
  return questions;
}

// ---------------- BUILD QUIZ: FAMILY LEVEL ----------------------------

async function buildFamilyQuizQuestionsFromVocab() {
  const neededDistractors = CONFIG.OPTIONS_PER_QUESTION - 1;
  const questions = [];

  const availableGroups = Object.entries(familyVocabByGroup).filter(
    ([, list]) => list && list.length > neededDistractors
  );

  console.log(
    "Available groups for family quiz:",
    availableGroups.map(([k, list]) => [k, list.length])
  );

  if (!availableGroups.length) {
    console.warn(
      "No groups with enough families to build family-level questions."
    );
    return [];
  }

  let attempts = 0;
  const MAX_ATTEMPTS = 200;

  while (
    questions.length < CONFIG.QUESTIONS_COUNT &&
    attempts < MAX_ATTEMPTS
  ) {
    attempts++;

    const [groupKey, familyList] =
      availableGroups[Math.floor(Math.random() * availableGroups.length)];
    if (!familyList || familyList.length <= neededDistractors) continue;

    const correctFamily =
      familyList[Math.floor(Math.random() * familyList.length)];
    const repSpecies = correctFamily.representative;
    const ex = repSpecies.exampleObservation;
    if (!ex || !ex.photoUrl) {
      console.warn(
        "No exampleObservation for representative of family",
        correctFamily.familyName,
        "– skipping."
      );
      continue;
    }

    const pool = familyList.filter(
      (f) => f.familyName !== correctFamily.familyName
    );
    if (pool.length < neededDistractors) continue;

    const distractorFamilies = pickRandomSubset(pool, neededDistractors);
    
const sweName = correctFamily.swedishName;
const formattedSwe =
  correctFamily.useExampleSpeciesName && sweName
    ? `t.ex. ${sweName}`
    : sweName;

const options = [
  {
    key: correctFamily.familyName,
    labelSci: correctFamily.familyName,
    labelSwe: formattedSwe,
  },
  ...distractorFamilies.map((f) => {
    const dswe = f.swedishName;
    const formatted =
      f.useExampleSpeciesName && dswe ? `t.ex. ${dswe}` : dswe;
    return {
      key: f.familyName,
      labelSci: f.familyName,
      labelSwe: formatted,
    };
  })
];


    questions.push({
      correct: {
        answerKey: correctFamily.familyName,
        labelSci: correctFamily.familyName,
        labelSwe: correctFamily.swedishName,

        obsId: ex.obsId,
        photoUrl: ex.photoUrl,
        observer: ex.observer || "okänd",
        licenseCode: ex.licenseCode || null,
        obsUrl: ex.obsUrl || "#",
        groupKey,
      },
      options: shuffleArray(options),
    });
  }

  console.log(
    `Family quiz: built ${questions.length} questions after ${attempts} attempts`
  );
  return questions;
}

// ---------------- REBUILD QUIZ FOR CURRENT LEVEL ----------------------

async function rebuildQuizForCurrentLevel() {
  statusEl.textContent = "Bygger frågor från vokabulären…";
  quizQuestions = [];

  if (currentLevel === "species") {
    quizQuestions = await buildSpeciesQuizQuestionsFromVocab();
  } else if (currentLevel === "genus") {
    quizQuestions = await buildGenusQuizQuestionsFromVocab();
  } else if (currentLevel === "family") {
    quizQuestions = await buildFamilyQuizQuestionsFromVocab();
  }

  currentIndex = 0;
  score = 0;

  if (!quizQuestions.length) {
    statusEl.textContent =
      "Kunde inte skapa några frågor. Testa en annan nivå eller kontrollera JSON-filerna.";
    questionContainerEl.classList.add("hidden");
    nextBtn.classList.add("hidden");
    return;
  }

  renderQuestion();
}

// ---------------- RENDERING -------------------------------------------

function renderQuestion() {
  const total = quizQuestions.length;
  if (!total) {
    statusEl.textContent =
      "Kunde inte skapa några frågor. Kontrollera JSON-filerna.";
    questionContainerEl.classList.add("hidden");
    nextBtn.classList.add("hidden");
    return;
  }

  if (currentIndex >= total) {
    renderFinished();
    return;
  }

  const { correct, options } = quizQuestions[currentIndex];

  statusEl.textContent = "";
  controlsEl && controlsEl.classList.remove("hidden");
  progressEl.textContent = `Fråga ${currentIndex + 1} av ${total}`;
  scoreEl.textContent = `Poäng: ${score} / ${total}`;

  // Grey out image while loading
  imageWrapperEl && imageWrapperEl.classList.add("loading-image");
  photoEl.onload = () => {
    imageWrapperEl && imageWrapperEl.classList.remove("loading-image");
  };

  photoEl.src = correct.photoUrl;
  photoEl.alt = "Observation photo";

  const licenseText = correct.licenseCode
    ? `License: ${String(correct.licenseCode).toUpperCase()}`
    : "License: okänd";

  attributionEl.innerHTML = `
    Foto: <a href="${correct.obsUrl}" target="_blank" rel="noopener">
      iNaturalist observation #${correct.obsId}
    </a> av <strong>${correct.observer}</strong>.
    <br />
    ${licenseText}
  `;


// Answers
answersEl.innerHTML = "";
options.forEach((opt) => {
  const btn = document.createElement("button");
  btn.className = "answer-btn";
  // Allow HTML so we can italicize scientific names
  btn.innerHTML = formatLabel(opt.labelSci, opt.labelSwe);
  btn.dataset.key = opt.key;
  btn.addEventListener("click", () => handleAnswerClick(btn, correct));
  answersEl.appendChild(btn);
});

nextBtn.classList.add("hidden");
questionContainerEl.classList.remove("hidden");
}

function handleAnswerClick(clickedBtn, correct) {
  const buttons = answersEl.querySelectorAll(".answer-btn");
  buttons.forEach((b) => {
    b.classList.add("disabled");
    b.disabled = true;
  });

  const chosenKey = clickedBtn.dataset.key;
  const correctKey = String(correct.answerKey);
  const isCorrect = chosenKey === correctKey;

  if (isCorrect) {
    clickedBtn.classList.add("correct");
    score += 1;
  } else {
    clickedBtn.classList.add("incorrect");
    buttons.forEach((b) => {
      if (b.dataset.key === correctKey) {
        b.classList.add("correct");
      }
    });
  }

  const label = formatLabel(correct.labelSci, correct.labelSwe);

  let levelWord = "art";
  if (currentLevel === "genus") levelWord = "släkte";
  else if (currentLevel === "family") levelWord = "familj";

  statusEl.innerHTML = `Korrekt ${levelWord}: ${label}`;

  nextBtn.classList.remove("hidden");
  scoreEl.textContent = `Poäng: ${score} / ${quizQuestions.length}`;
}

function renderFinished() {
  questionContainerEl.classList.add("hidden");
  nextBtn.classList.add("hidden");

  const total = quizQuestions.length;
  statusEl.innerHTML = `
    Quiz klart! Slutpoäng: <strong>${score} / ${total}</strong>.
  `;
  progressEl.textContent = "";
}

// ---------------- INIT & EVENTS ---------------------------------------

async function initQuiz() {
  statusEl.textContent = "Laddar vokabulär från JSON-filer…";

  try {
    await loadVocab();
    buildGenusVocabFromSpecies();
    buildFamilyVocabFromSpecies();

    if (levelSelectEl) {
      levelSelectEl.value = currentLevel;
    }

    await rebuildQuizForCurrentLevel();
  } catch (err) {
    console.error(err);
    statusEl.textContent =
      "Fel vid laddning av data. Se konsolen för detaljer.";
  }
}

nextBtn.addEventListener("click", () => {
  imageWrapperEl && imageWrapperEl.classList.add("loading-image");
  currentIndex += 1;
  renderQuestion();
});

if (levelSelectEl) {
  levelSelectEl.addEventListener("change", async () => {
    currentLevel = levelSelectEl.value || "species";
    await rebuildQuizForCurrentLevel();
  });
}

// Start the quiz
initQuiz();
