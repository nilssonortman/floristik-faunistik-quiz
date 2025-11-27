// ==== CONFIG ============================================================
const CONFIG = {
  // Default project: your 2025 course project
  DEFAULT_PROJECT_SLUG:
    "2025-floristik-och-faunistik-pa-kau-big001-bigbi1-bign10",

  QUESTIONS_COUNT: 10,
  OPTIONS_PER_QUESTION: 4,
  REQUIRE_RESEARCH_GRADE: true,

  ALLOWED_LICENSES: ["cc0", "cc-by", "cc-by-nc"],

  // Broad group detection (for mapping to vocab groups)
  GROUP_RANK_PRIORITY: ["class", "phylum", "division", "kingdom"],
};

// ==== STATE =============================================================
let observations = [];
let quizQuestions = [];
let currentIndex = 0;
let score = 0;
let currentLevel = "species"; // "species" | "genus" | "family"

// External vocabularies (top genera per group in Sweden)
const externalDistractors = {
  insects: [],
  plants: [],
  mosses: [],
  lichens: [],
  mammals: [],
  birds: [],
  fungi: [],
  spiders: [],
};

// ==== DOM ELEMENTS ======================================================
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

// ==== HELPERS ===========================================================

function getProjectSlugFromUrl() {
  const params = new URLSearchParams(window.location.search);
  return (
    params.get("project") ||
    params.get("project_id") ||
    CONFIG.DEFAULT_PROJECT_SLUG
  );
}

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
  const shuffled = shuffleArray(array);
  return shuffled.slice(0, n);
}

function licenseIsAllowed(code) {
  if (!code) return false;
  return CONFIG.ALLOWED_LICENSES.includes(code.toLowerCase());
}

function buildPhotoUrl(photo) {
  if (!photo || !photo.url) return null;
  return photo.url.replace("square.", "large.");
}

// Group label for an observation depending on quiz level
function getGroupLabelForObs(obs) {
  switch (currentLevel) {
    case "genus":
      return obs.genusName || obs.scientificName;
    case "family":
      return obs.familyName || null;
    case "species":
    default:
      return obs.scientificName;
  }
}

// Text shown on answer buttons
function formatAnswerText(obs) {
  const groupLabel = getGroupLabelForObs(obs) || obs.scientificName;
  if (obs.swedishName) return `${groupLabel} (${obs.swedishName})`;
  return groupLabel;
}

// Map broad taxonomic group (class/phylum/…) to our didactic/vocab group keys
function mapBroadGroupToDidacticGroup(broadGroupName) {
  if (!broadGroupName) return null;

  // Animals
  if (broadGroupName === "Insecta") return "insects";
  if (broadGroupName === "Aves") return "birds";
  if (broadGroupName === "Mammalia") return "mammals";
  if (broadGroupName === "Araneae") return "spiders"; // in practice a "order" ancestor may be the first rank

  // Plants
  if (broadGroupName === "Plantae" || broadGroupName === "Tracheophyta")
    return "plants";

  // Mosses (bryophytes)
  if (
    broadGroupName === "Bryophyta" ||
    broadGroupName === "Marchantiophyta" ||
    broadGroupName === "Anthocerotophyta"
  )
    return "mosses";

  // Fungi
  if (broadGroupName === "Fungi") return "fungi";

  // Lichens – main lichen class
  if (broadGroupName === "Lecanoromycetes") return "lichens";

  return null;
}

// ==== LOAD EXTERNAL VOCAB =================================================

async function loadExternalDistractors() {
  const files = {
    insects: "data/insects_genera_sweden.json",
    plants: "data/plants_genera_sweden.json",
    mosses: "data/mosses_genera_sweden.json",
    lichens: "data/lichens_genera_sweden.json",
    mammals: "data/mammals_genera_sweden.json",
    birds: "data/birds_genera_sweden.json",
    fungi: "data/fungi_genera_sweden.json",
    spiders: "data/spiders_genera_sweden.json",
  };

  for (const [key, path] of Object.entries(files)) {
    try {
      const res = await fetch(path);
      if (!res.ok) {
        console.warn(`Failed to load ${path}: ${res.status}`);
        continue;
      }
      externalDistractors[key] = await res.json();
      console.log(
        `Loaded ${externalDistractors[key].length} vocab genera for ${key}`
      );
    } catch (e) {
      console.warn(`Error loading ${path}`, e);
    }
  }
}

// ==== FETCH & PREP DATA ===================================================

async function fetchObservations(projectSlug) {
  const baseUrl = "https://api.inaturalist.org/v1/observations";
  const params = new URLSearchParams({
    project_id: projectSlug,
    per_page: "200",
    order: "desc",
    order_by: "created_at",
    photos: "true",
    locale: "sv",
  });

  if (CONFIG.REQUIRE_RESEARCH_GRADE) {
    params.set("quality_grade", "research");
  }

  const url = `${baseUrl}?${params.toString()}`;

  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`iNaturalist API error: ${res.status} ${res.statusText}`);
  }
  const data = await res.json();
  return data.results || [];
}

function filterAndTransform(rawObs) {
  const result = [];

  for (const o of rawObs) {
    const taxon = o.taxon;
    if (!taxon) continue;

    const photos = o.photos || [];
    if (!photos.length) continue;

    if (CONFIG.REQUIRE_RESEARCH_GRADE && o.quality_grade !== "research") {
      continue;
    }

    if (o.license_code && !licenseIsAllowed(o.license_code)) {
      continue;
    }

    const photo = photos.find((p) => licenseIsAllowed(p.license_code));
    if (!photo) continue;

    const photoUrl = buildPhotoUrl(photo);
    if (!photoUrl) continue;

    const scientificName = taxon.name || "";
    if (!scientificName) continue;

    const genusName = scientificName.split(" ")[0] || scientificName;

    result.push({
      obsId: o.id,
      taxonId: taxon.id,
      photoUrl,
      scientificName,
      swedishName: taxon.preferred_common_name || null,
      genusName,
      familyName: null,
      broadGroup: null,
      didacticGroup: null,
      observer: (o.user && o.user.login) || "unknown",
      licenseCode: photo.license_code || o.license_code || null,
      obsUrl: `https://www.inaturalist.org/observations/${o.id}`,
    });
  }

  return result;
}

// Enrich observations with family and broadGroup via /v1/taxa
async function enrichWithTaxaData(obsList) {
  const ids = [
    ...new Set(
      obsList
        .map((o) => o.taxonId)
        .filter((id) => id !== null && id !== undefined)
    ),
  ];

  if (!ids.length) return;

  const familyMap = new Map();
  const broadGroupMap = new Map();
  const chunkSize = 30;

  for (let i = 0; i < ids.length; i += chunkSize) {
    const chunk = ids.slice(i, i + chunkSize);
    const url = `https://api.inaturalist.org/v1/taxa/${chunk.join(
      ","
    )}?locale=sv`;
    try {
      const res = await fetch(url);
      if (!res.ok) continue;
      const data = await res.json();
      const taxa = data.results || [];

      for (const t of taxa) {
        let famName = null;
        let broadGroup = null;

        if (t.rank === "family") {
          famName = t.name;
        } else if (Array.isArray(t.ancestors)) {
          const fam = t.ancestors.find((a) => a.rank === "family");
          if (fam) famName = fam.name;
        }

        if (Array.isArray(t.ancestors)) {
          for (const rank of CONFIG.GROUP_RANK_PRIORITY) {
            const anc = t.ancestors.find((a) => a.rank === rank);
            if (anc) {
              broadGroup = anc.name;
              break;
            }
          }
        }

        if (famName) familyMap.set(t.id, famName);
        if (broadGroup) broadGroupMap.set(t.id, broadGroup);
      }
    } catch (err) {
      console.warn("Error enriching taxa chunk:", err);
    }
  }

  obsList.forEach((o) => {
    o.familyName = familyMap.get(o.taxonId) || null;
    o.broadGroup = broadGroupMap.get(o.taxonId) || null;
    o.didacticGroup = mapBroadGroupToDidacticGroup(o.broadGroup);
  });
}

// ==== BUILD QUIZ QUESTIONS (genus uses vocab) =============================

function buildQuizQuestions(obsList) {
  // Collapse to unique groups for this level
  const groupsMap = new Map(); // groupLabel -> { label, obs, broadGroup, didacticGroup }

  for (const obs of obsList) {
    const label = getGroupLabelForObs(obs);
    if (!label) continue;

    if (!groupsMap.has(label)) {
      groupsMap.set(label, {
        label,
        obs,
        broadGroup: obs.broadGroup || null,
        didacticGroup: obs.didacticGroup || null,
      });
    }
  }

  const groups = Array.from(groupsMap.values());
  if (!groups.length) return [];

  const neededDistractors = CONFIG.OPTIONS_PER_QUESTION - 1;
  const questions = [];

  for (const g of shuffleArray(groups)) {
    if (questions.length >= CONFIG.QUESTIONS_COUNT) break;

    const correctObs = g.obs;
    const correctBroad = g.broadGroup;
    const didacticGroup = g.didacticGroup;

    if (!correctBroad) continue;

    // -------------------------------------------------------------------
    // GENUS MODE: correct = project genus, distractors = external vocab
    // -------------------------------------------------------------------
    if (currentLevel === "genus") {
      if (!didacticGroup) continue;

      const vocabList = externalDistractors[didacticGroup];
      if (!vocabList || !vocabList.length) continue;

      const correctGenusLabel = getGroupLabelForObs(correctObs);
      if (!correctGenusLabel) continue;

      const vocabClean = vocabList.filter(
        (v) => v.scientificName !== correctGenusLabel
      );

      if (vocabClean.length < neededDistractors) continue;

      const chosenVocab = pickRandomSubset(vocabClean, neededDistractors);

      const distractorObs = chosenVocab.map((v) => ({
        obsId: null,
        taxonId: null,
        photoUrl: null,
        scientificName: v.scientificName,
        swedishName: v.swedishName || null,
        genusName: v.scientificName,
        familyName: null,
        broadGroup: correctBroad,
        didacticGroup,
        observer: "external",
        licenseCode: null,
        obsUrl: null,
      }));

      const options = shuffleArray([correctObs, ...distractorObs]);

      questions.push({
        correct: correctObs,
        options,
      });
      continue;
    }

    // -------------------------------------------------------------------
    // SPECIES / FAMILY MODE: project-based same-broadGroup distractors
    // -------------------------------------------------------------------
    const projectCandidates = groups.filter(
      (x) => x.label !== g.label && x.broadGroup === correctBroad
    );
    if (projectCandidates.length < neededDistractors) continue;

    const distractors = pickRandomSubset(
      projectCandidates.map((cg) => cg.obs),
      neededDistractors
    );

    const options = shuffleArray([correctObs, ...distractors]);

    questions.push({
      correct: correctObs,
      options,
    });
  }

  return questions;
}

// ==== RENDERING ===========================================================

function renderQuestion() {
  const total = quizQuestions.length;
  if (currentIndex >= total) {
    renderFinished();
    return;
  }

  const { correct, options } = quizQuestions[currentIndex];
  const correctLabel = getGroupLabelForObs(correct) || correct.scientificName;

  statusEl.textContent = "";
  controlsEl.classList.remove("hidden");
  progressEl.textContent = `Question ${currentIndex + 1} of ${total}`;
  scoreEl.textContent = `Score: ${score} / ${total}`;

  // Image: grey out while loading new image
  imageWrapperEl.classList.add("loading-image");
  photoEl.onload = () => {
    imageWrapperEl.classList.remove("loading-image");
  };

  photoEl.src = correct.photoUrl;
  photoEl.alt = "Observation photo";

  const licenseText = correct.licenseCode
    ? `License: ${correct.licenseCode.toUpperCase()}`
    : "License: unknown";

  attributionEl.innerHTML = `
    Photo: <a href="${correct.obsUrl}" target="_blank" rel="noopener">
      iNaturalist observation #${correct.obsId}
    </a> by <strong>${correct.observer}</strong>.
    <br />
    ${licenseText}
  `;

  answersEl.innerHTML = "";
  options.forEach((opt) => {
    const btn = document.createElement("button");
    const label = getGroupLabelForObs(opt) || opt.scientificName;
    btn.className = "answer-btn";
    btn.textContent = formatAnswerText(opt);
    btn.dataset.groupLabel = label;
    btn.addEventListener("click", () =>
      handleAnswerClick(btn, correct, correctLabel)
    );
    answersEl.appendChild(btn);
  });

  nextBtn.classList.add("hidden");
  questionContainerEl.classList.remove("hidden");
}

function handleAnswerClick(clickedBtn, correct, correctLabel) {
  const buttons = answersEl.querySelectorAll(".answer-btn");
  buttons.forEach((b) => {
    b.classList.add("disabled");
    b.disabled = true;
  });

  const chosenLabel = clickedBtn.dataset.groupLabel;
  const isCorrect = chosenLabel === correctLabel;

  if (isCorrect) {
    clickedBtn.classList.add("correct");
    score += 1;
  } else {
    clickedBtn.classList.add("incorrect");
    buttons.forEach((b) => {
      if (b.dataset.groupLabel === correctLabel) {
        b.classList.add("correct");
      }
    });
  }

  const sci = correct.scientificName;
  const swe = correct.swedishName ? ` (${correct.swedishName})` : "";
  const groupLabel = getGroupLabelForObs(correct) || sci;
  const levelName =
    currentLevel === "species"
      ? "art"
      : currentLevel === "genus"
      ? "släkte"
      : "familj";

  statusEl.textContent = `Korrekt ${levelName}: ${groupLabel}${swe}`;

  nextBtn.classList.remove("hidden");
  scoreEl.textContent = `Score: ${score} / ${quizQuestions.length}`;
}

function renderFinished() {
  questionContainerEl.classList.add("hidden");
  nextBtn.classList.add("hidden");

  const total = quizQuestions.length;
  statusEl.innerHTML = `
    Quiz finished! Final score: <strong>${score} / ${total}</strong>.
  `;
  progressEl.textContent = "";
}

// Rebuild quiz when level changes
function rebuildQuizForCurrentLevel() {
  if (!observations.length) return;
  quizQuestions = buildQuizQuestions(observations);
  currentIndex = 0;
  score = 0;

  if (!quizQuestions.length) {
    statusEl.textContent =
      "Not enough distinct groups to create a quiz at this level. Try another level or add more observations.";
    questionContainerEl.classList.add("hidden");
    nextBtn.classList.add("hidden");
    return;
  }

  renderQuestion();
}

// ==== INIT ===============================================================

async function initQuiz() {
  const projectSlug = getProjectSlugFromUrl();
  statusEl.textContent = `Loading observations from project "${projectSlug}"…`;

  levelSelectEl.value = currentLevel;

  try {
    await loadExternalDistractors();

    const raw = await fetchObservations(projectSlug);
    let filtered = filterAndTransform(raw);

    if (!filtered.length) {
      statusEl.textContent =
        "No suitable observations found (with photos and allowed licenses).";
      return;
    }

    try {
      await enrichWithTaxaData(filtered);
    } catch (err) {
      console.warn("Taxa enrichment failed, continuing without:", err);
    }

    observations = filtered;
    quizQuestions = buildQuizQuestions(observations);
    currentIndex = 0;
    score = 0;

    if (!quizQuestions.length) {
      statusEl.textContent =
        "Not enough distinct taxa to create a quiz. Add more observations or switch level.";
      return;
    }

    renderQuestion();
  } catch (err) {
    console.error(err);
    statusEl.textContent =
      "Error loading data from iNaturalist. See console for details.";
  }
}

// Next button handler
nextBtn.addEventListener("click", () => {
  imageWrapperEl.classList.add("loading-image");
  currentIndex += 1;
  renderQuestion();
});

// Level selector handler
if (levelSelectEl) {
  levelSelectEl.addEventListener("change", () => {
    currentLevel = levelSelectEl.value;
    rebuildQuizForCurrentLevel();
  });
}

// Start
initQuiz();
