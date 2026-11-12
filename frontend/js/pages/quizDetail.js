// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
/* Quiz detail: hero, actions, and tabbed sections (overview, statistics,
   versions, AI reviews). The author also gets audience statistics; a visitor
   only sees what is needed to decide whether to play. */

import { api } from "../api.js";
import { mountPlayer } from "../audio.js";
import { framingAttr, paintFraming } from "../imageFrame.js";
import { currentLanguage, languageLabel, t, tp } from "../i18n.js";
import { navigate } from "../router.js";
import { isLoggedIn, state } from "../store.js";
import { flagStrip } from "../flags.js";
import { confirmDialog, escapeHtml, formatDate, toast } from "../ui.js";
import { setPageSeo, titleSlug } from "../seo.js";
import { assessmentSection, bindAssessment } from "./quizAssessment.js";
import { placeShare, shareCard, wireShare } from "../share.js";

const MODE_LABEL = {
  qcm: "editor.mode_qcm",
  swipe: "editor.mode_swipe",
  poll: "new_quiz.poll",
  adventure: "editor.mode_adventure",
};

export async function renderQuizDetail({ id, query }) {
  const root = document.createElement("div");
  root.innerHTML = `<div class="loading">${t("common.loading")}</div>`;

  let quiz;
  try {
    quiz = await api.get(`/api/v1/quizzes/${id}?lang=${encodeURIComponent(currentLanguage())}`);
  } catch (error) {
    root.innerHTML = `
      <div class="empty">
        <h2>${t("error.not_found")}</h2>
        <p class="muted">${escapeHtml(error.detail || "")}</p>
        <a class="btn mt-2" href="/" data-link>${t("action.back")}</a>
      </div>`;
    return root;
  }

  // Describe the page for the tab, the preview and the crawler that only reads
  // the first response: the server fills the shell, this keeps it true after a
  // client-side navigation.
  setPageSeo({
    title: quiz.title,
    description: (quiz.description || "").slice(0, 200),
    path: `/quizzes/${quiz.id}/${titleSlug(quiz.title, "quiz")}`,
    type: "article",
    jsonLd: {
      "@context": "https://schema.org",
      "@type": "Quiz",
      name: quiz.title,
      description: (quiz.description || "").slice(0, 200),
      url: `${location.origin}/quizzes/${quiz.id}/${titleSlug(quiz.title, "quiz")}`,
      inLanguage: quiz.default_language || "en",
      isAccessibleForFree: true,
    },
  });

  const isOwner = isLoggedIn() && state.user && (quiz.owner_id === state.user.id || state.user.is_staff);
  const status = quiz.status;
  const isStory = quiz.mode === "adventure";
  const languageList = quiz.languages || [quiz.default_language];
  const languages = languageList.map(languageLabel).join(", ");
  const sceneCount = (quiz.adventure?.nodes || []).length;
  const questionCount = isStory ? sceneCount : quiz.question_count;
  const tabs = [
    { key: "overview", label: t("quiz.tab_overview") },
    ...(isStory ? [] : [{ key: "questions", label: t("quiz.tab_questions") }]),
    ...(isOwner ? [{ key: "stats", label: t("quiz.tab_stats") }] : []),
    ...(isOwner ? [{ key: "versions", label: t("quiz.tab_versions") }] : []),
    { key: "reviews", label: t("quiz.reviews") },
  ];
  const initialTab = tabs.some((tab) => tab.key === (query && query.tab)) ? query.tab : "overview";

  const reviews = await api.get(`/api/v1/quizzes/${id}/reviews`).catch(() => null);
  const versions = isOwner
    ? await api.get(`/api/v1/quizzes/${id}/versions`).catch(() => [])
    : [];
  const stats = isOwner ? await api.get(`/api/v1/quizzes/${id}/stats`).catch(() => null) : null;
  // A poll is read through its answer distribution, not through a success rate.
  const poll = isOwner && quiz.mode === "poll"
    ? await api.get(`/api/v1/quizzes/${id}/results`).catch(() => null)
    : null;

  const questionPreview = (question, index, withStats) => {
    const stat = withStats
      ? (stats.questions || []).find((row) => row.source_question_id === question.id) || null
      : null;
    const rate = stat ? Math.round(stat.correct_rate * 100) : 0;
    return `
      <article class="q-preview">
        <div class="q-preview-head">
          <span class="q-index">${index + 1}</span>
          <div class="q-meta">
            <span class="badge muted">${question.time_limit_seconds}s</span>
            <span class="badge muted">${question.points} ${t("common.points")}</span>
            ${stat ? `<span class="badge ${rate >= 60 ? "ok" : rate >= 30 ? "warn" : "danger"}">${rate}% ${t("quiz.correct_short")}</span>` : ""}
          </div>
        </div>
        <div class="question-text">${question.text_html}</div>
        ${
          question.image_path
            ? `<img class="question-image" src="${escapeHtml(question.image_path)}" alt="" loading="lazy"${framingAttr(question.image_framing)} />`
            : ""
        }
        <ul class="answer-list">
          ${question.options
            .map(
              (option) => `
            <li class="${option.is_correct && isOwner ? "is-correct" : ""}">
              ${option.is_correct && isOwner ? '<span class="badge ok">✓</span>' : ""}
              ${escapeHtml(option.text)}
              ${Object.keys(option.translations || {}).length ? `<span class="small-note">(${Object.keys(option.translations).map(languageLabel).join(", ")})</span>` : ""}
            </li>`,
            )
            .join("")}
        </ul>
      </article>`;
  };

  const overviewPanel = () => `
    ${
      isStory
        ? `<section class="card">
            <div class="card-head"><h3>${t("quiz.story_map")}</h3></div>
            <p class="muted small">${t("quiz.story_summary", {
              nodes: sceneCount,
              endings: (quiz.adventure?.nodes || []).filter((node) => node.kind === "ending").length,
            })}</p>
            <div class="row-wrap mt-2">
              ${(quiz.adventure?.attributes || [])
                .map(
                  (attribute) =>
                    `<span class="badge muted">${escapeHtml(attribute.label)} · ${attribute.initial_value} / ${attribute.max_value ?? "—"}</span>`,
                )
                .join("")}
            </div>
            <p class="hint mt-2">${t("quiz.story_preview_hint", { n: sceneCount })}</p>
          </section>`
        : `<section class="card">
            <div class="card-head">
              <h3>${t("quiz.first_questions")}</h3>
              <span class="badge muted">${questionCount} ${t(questionCount === 1 ? "common.question" : "common.questions")}</span>
            </div>
            <div class="q-preview-list">
              ${quiz.questions.slice(0, 3).map((question, index) => questionPreview(question, index, false)).join("")}
            </div>
            ${
              questionCount > 3
                ? `<button class="btn btn-sm btn-ghost mt-2" data-tab-jump="questions">${t("quiz.see_all", { n: questionCount })}</button>`
                : ""
            }
          </section>`
    }`;

  const questionsPanel = () => `
    <section class="card">
      <div class="card-head">
        <h3>${t("quiz.tab_questions")}</h3>
        <span class="badge muted">${questionCount}</span>
      </div>
      <div class="q-preview-list">
        ${quiz.questions.map((question, index) => questionPreview(question, index, false)).join("")}
      </div>
    </section>`;

  const pollPanel = () => {
    if (!poll) return `<div class="banner warn">${t("common.error")}</div>`;
    if (!poll.respondents) {
      return `<section class="card center">
        <h3>${t("quiz.no_stats_yet")}</h3>
        <p class="muted">${t("quiz.no_stats_hint")}</p>
      </section>`;
    }
    const audience = { private: t("editor.results_private"), respondents: t("editor.results_respondents"), public: t("editor.results_public") }[poll.results_visibility] || "";
    return `
      <div class="stat-grid">
        ${statCard(t("quiz.stat_participants"), poll.respondents, t("quiz.stat_participants_hint"))}
        ${statCard(t("quiz.poll_questions"), poll.questions.length, t("quiz.poll_questions_hint"))}
        ${statCard(t("quiz.poll_audience"), audience, t("quiz.poll_audience_hint"))}
      </div>
      ${poll.questions
        .map(
          (row) => `
        <section class="card mt-3">
          <div class="card-head">
            <h3><span class="q-index">${row.index}</span> <span class="q-inline">${row.text_html}</span></h3>
            <span class="badge muted">${tp("quiz.poll_one_answer", "quiz.poll_answers", row.respondents)}</span>
            ${row.allow_multiple ? `<span class="badge">${t("editor.poll_multiple")}</span>` : ""}
          </div>
          ${
            row.respondents
              ? `<div class="bar-list">
                  ${row.options
                    .map((option) => {
                      const percent = Math.round((option.share || 0) * 100);
                      return `
                        <div class="bar-row">
                          <div class="bar-label"><span>${escapeHtml(option.text)}</span><span class="muted">${option.count} · ${percent}%</span></div>
                          <div class="bar-track"><div class="bar-fill" data-width="${percent}"></div></div>
                        </div>`;
                    })
                    .join("")}
                 </div>`
              : `<p class="muted">${t("editor.poll_results_empty")}</p>`
          }
        </section>`,
        )
        .join("")}`;
  };

  const statsPanel = () => {
    if (quiz.mode === "poll") return pollPanel();
    if (!stats) return `<div class="banner warn">${t("common.error")}</div>`;
    if (!stats.sessions) {
      // An adventure is played alone, by design: offering a live room here led
      // to "This quiz has no question yet." on a mode that has no questions to
      // project. The empty state invites a solo run instead.
      const cta =
        quiz.mode === "adventure"
          ? `<a class="btn btn-primary mt-2" href="/adventures/${quiz.id}/play" data-link>${t("quiz.play_story")}</a>`
          : quiz.mode === "swipe"
            ? `<button class="btn btn-primary mt-2" data-act="solo">${t("quiz.play_solo")}</button>`
            : `<button class="btn btn-primary mt-2" data-act="live">${t("quiz.host_live")}</button>`;
      return `<section class="card center">
        <h3>${t("quiz.no_stats_yet")}</h3>
        <p class="muted">${t("quiz.no_stats_hint")}</p>
        ${cta}
      </section>`;
    }
    const rate = Math.round(stats.correct_rate * 100);
    return `
      <div class="stat-grid">
        ${statCard(t("quiz.stat_participants"), stats.participants, t("quiz.stat_participants_hint"))}
        ${statCard(
          t("quiz.stat_sessions"),
          stats.sessions,
          tp("quiz.stat_sessions_hint_one", "quiz.stat_sessions_hint", stats.finished_sessions),
        )}
        ${statCard(t("quiz.stat_correct"), `${rate}%`, t("quiz.stat_correct_hint", { n: stats.answers }))}
        ${statCard(t("quiz.stat_avg_score"), stats.average_score, t("quiz.stat_avg_score_hint"))}
      </div>
      <section class="card mt-3">
        <div class="card-head">
          <h3>${t("quiz.per_question")}</h3>
          <span class="badge muted">${t("quiz.questions_measured", {
            n: stats.questions.length,
            total: stats.total_questions ?? stats.questions.length,
          })}</span>
          <span class="badge muted">${t("quiz.avg_time")} ${stats.average_seconds}s</span>
        </div>
        ${
          stats.questions.length
            ? `<div class="bar-list">
                ${stats.questions
                  .map((row) => {
                    const percent = Math.round(row.correct_rate * 100);
                    const tone = percent >= 60 ? "ok" : percent >= 30 ? "warn" : "danger";
                    return `
                      <div class="bar-row">
                        <div class="bar-label">
                          <span class="q-index">${row.index}</span>
                          <span class="bar-text">${row.text_html}</span>
                          <span class="bar-value">${percent}%</span>
                        </div>
                        <div class="bar-track"><div class="bar-fill ${tone}" data-width="${percent}"></div></div>
                        <p class="small-note">${t("quiz.answered_of", {
                          correct: row.correct,
                          answered: row.answered,
                        })} · ${t("quiz.avg_time")} ${row.average_seconds}s</p>
                      </div>`;
                  })
                  .join("")}
              </div>`
            : `<p class="muted">${t("quiz.no_stats_yet")}</p>`
        }
      </section>`;
  };

  const versionsPanel = () => `
    <section class="card">
      <div class="card-head">
        <h3>${t("quiz.tab_versions")}</h3>
        <span class="badge ${quiz.published_version ? "ok" : "muted"}">
          ${quiz.published_version ? t("editor.live_version", { n: quiz.published_version }) : t("editor.no_live_version")}
        </span>
      </div>
      ${
        versions.length
          ? `<div class="version-list">
              ${versions
                .map(
                  (version) => `
                <div class="version-row ${version.number === quiz.published_version ? "is-live" : ""}">
                  <div>
                    <strong>v${version.number}</strong>
                    <span class="badge ${version.status === "published" ? "ok" : version.status === "pending" ? "warn" : "muted"}">
                      ${t(`editor.version_status.${version.status}`)}
                    </span>
                    ${
                      version.number === quiz.published_version
                        ? `<span class="badge ok">${t("editor.version_live")}</span>`
                        : ""
                    }
                  </div>
                  <div class="version-meta muted small">
                    ${formatDate(version.published_at || version.created_at)}
                    · ${version.question_count ?? ""} ${t(version.question_count === 1 ? "common.question" : "common.questions")}
                  </div>
                  <div class="row">
                    ${
                      version.number === quiz.published_version
                        ? ""
                        : `<button class="btn btn-sm btn-ghost" data-restore="${version.number}">${t("editor.version_restore")}</button>`
                    }
                  </div>
                </div>`,
                )
                .join("")}
            </div>`
          : `<p class="muted">${t("quiz.no_versions")}</p>`
      }
    </section>`;

  const reviewsPanel = () =>
    reviews
      ? `<section class="card">
          <div class="card-head">
            <h3>${t("quiz.reviews")}</h3>
            <span class="badge muted">${reviews.ai_available ? `<span aria-hidden="true">✨</span> ${t("editor.ai_title")}` : t("editor.ai_unavailable")}</span>
          </div>
          <div class="row-wrap">
            ${
              reviews.legal_status
                ? `<span class="pill ${reviews.legal_status === "blocked" ? "rejected" : "public"}">${
                    reviews.legal_status === "blocked" ? t("quiz.legal_blocked") : t("quiz.legal_approved")
                  }</span>`
                : ""
            }
            ${
              reviews.answer_status
                ? `<span class="pill ${reviews.answer_status === "corrected" ? "pending" : "public"}">${
                    reviews.answer_status === "corrected" ? t("quiz.answers_corrected") : t("quiz.answers_ok")
                  }</span>`
                : ""
            }
          </div>
          ${
            isOwner && reviews.ai_available
              ? `<div class="row-wrap mt-2 ai-zone">
                   <button class="btn btn-sm" data-act="ai-legal"><span aria-hidden="true">✨</span> ${t("quiz.ai_legal_review")}</button>
                   <button class="btn btn-sm" data-act="ai-answers"><span aria-hidden="true">✨</span> ${t("quiz.ai_answer_review")}</button>
                   <button class="btn btn-sm btn-ghost" data-act="ai-apply" ${
                     reviews.answer_status === "corrected" ? "" : "hidden"
                   }>${t("editor.ai_apply")}</button>
                 </div>`
              : ""
          }
          ${
            (reviews.reviews || []).length
              ? `<div class="mt-2">${reviews.reviews
                  .map(
                    (review) => `
                <div class="review-item ${escapeHtml(review.status)}">
                  <strong>${escapeHtml(review.kind)}</strong> — ${escapeHtml(review.status)}
                  ${review.stale ? `<span class="badge warn">${t("quiz.stale")}</span>` : ""}
                  <div class="finding">${escapeHtml(review.summary || "")}</div>
                </div>`,
                  )
                  .join("")}</div>`
              : `<p class="muted small mt-2">${t("admin.no_reviews")}</p>`
          }
        </section>`
      : `<div class="banner warn">${t("common.error")}</div>`;

  const panelFor = (key) => {
    if (key === "questions") return questionsPanel();
    if (key === "stats") return statsPanel();
    if (key === "versions") return versionsPanel();
    if (key === "reviews") return reviewsPanel();
    return overviewPanel();
  };

  root.innerHTML = `
    <div class="detail">
      <header class="detail-hero">
        <div class="detail-hero-main">
          <a class="muted small" href="${isOwner ? "/dashboard" : "/"}" data-link>← ${
            isOwner ? t("nav.dashboard") : t("nav.home")
          }</a>
          <div class="row-wrap mt-1">
            <span class="pill ${escapeHtml(status)}">${t(`dash.status.${status}`)}</span>
            <span class="badge muted">${t(MODE_LABEL[quiz.mode] || MODE_LABEL.qcm)}</span>
            ${
              quiz.published_version
                ? `<span class="badge ok">${t("editor.live_version", { n: quiz.published_version })}</span>`
                : ""
            }
            ${quiz.ai_generated ? `<span class="pill ai">${t("quiz.ai_generated")}</span>` : ""}
          </div>
          <h1 class="mt-2">${escapeHtml(quiz.title)}</h1>
          <p class="muted detail-description">${escapeHtml(quiz.description || "")}</p>
          ${isStory ? "" : `<p class="detail-hint small">${t("quiz.host_hint")}</p>`}
          <div class="audio-host" id="quiz-audio"></div>
          <section class="card detail-wiki" id="quiz-wikis" hidden>
            <h2 class="detail-wiki-title">${t("wiki.read_first")}</h2>
            <div class="wiki-quiz-list" id="quiz-wikis-list"></div>
          </section>
          <div class="detail-actions">
            ${
              isStory
                ? `<a class="btn btn-primary" href="/adventures/${quiz.id}/play" data-link>${t("quiz.play_story")}</a>`
                : `<button class="btn btn-primary btn-lg" data-act="solo">${t("quiz.play_solo")}</button>
                   <div class="host-actions" role="group" aria-label="${t("quiz.host_group")}">
                     <span class="host-actions-caption">${t("quiz.host_group")}</span>
                     <div class="host-actions-row">
                       <button class="btn btn-quiet" data-act="live" title="${t("quiz.host_group_hint")}">${t("quiz.host_live")}</button>
                       <button class="btn btn-quiet" data-act="live-play" title="${t("quiz.host_group_hint")}">${t("quiz.host_and_play")}</button>
                     </div>
                   </div>`
            }
          </div>
        </div>
        <aside class="detail-aside">
          <div class="card">
            <h3>${t("quiz.about")}</h3>
            <dl class="fact-list">
              <div><dt>${t("common.owner")}</dt><dd>${escapeHtml(quiz.owner_name || "—")}</dd></div>
              <div><dt>${isStory ? t("quiz.scenes") : t("common.questions")}</dt><dd>${questionCount}</dd></div>
              <div><dt>${t("editor.policy_label")}</dt><dd>${
                quiz.wrong_answer_policy === "penalty"
                  ? t("editor.policy_penalty")
                  : t("quiz.policy_zero_short")
              }</dd></div>
              <div><dt>${t("quiz.languages")}</dt><dd class="row fact-langs">${flagStrip(languageList, quiz.default_language)}<span>${languages}</span></dd></div>
              <div><dt>${t("common.updated")}</dt><dd>${formatDate(quiz.updated_at)}</dd></div>
            </dl>
          </div>
          ${shareCard(`${window.location.origin}/quizzes/${quiz.id}`, {
            title: quiz.title,
            hint: t("share.qr_hint_quiz"),
          })}
          ${
            isOwner
              ? `<div class="card">
                  <h3>${t("quiz.owner_actions")}</h3>
                  ${
                    isStory
                      ? `<a class="btn btn-block" href="/adventures/${quiz.id}/edit" data-link>${t("quiz.edit_story")}</a>`
                      : `<a class="btn btn-block" href="/quizzes/${quiz.id}/edit" data-link>${t("quiz.edit")}</a>`
                  }
                  <div class="stack-sm">
                    ${
                      status !== "public"
                        ? `<button class="btn btn-sm btn-primary" data-act="publish">${
                            state.user && (state.user.is_trusted || state.user.is_staff)
                              ? t("quiz.publish")
                              : t("quiz.publish_request")
                          }</button>`
                        : `<button class="btn btn-sm btn-ghost" data-act="retire">${t("quiz.retire")}</button>`
                    }
                    <button class="btn btn-sm" data-act="duplicate">${t("quiz.duplicate")}</button>
                    <button class="btn btn-sm btn-danger" data-act="delete">${t("action.delete")}</button>
                  </div>
                </div>`
              : ""
          }
        </aside>
      </header>

      ${quiz.moderation_note ? `<div class="banner warn">${t("quiz.moderation_note")}: ${escapeHtml(quiz.moderation_note)}</div>` : ""}
      ${status !== "public" && !isOwner ? `<div class="banner warn">${t("quiz.not_published")}</div>` : ""}

      <nav class="tabs" role="tablist" aria-label="${escapeHtml(t("quiz.sections"))}">
        ${tabs
          .map(
            (tab) => `<button class="tab ${tab.key === initialTab ? "is-active" : ""}" role="tab"
                        aria-selected="${tab.key === initialTab}" data-tab="${tab.key}">${tab.label}</button>`,
          )
          .join("")}
      </nav>
      <div class="tab-panel" id="tab-panel">${panelFor(initialTab)}</div>
      <div class="share-mobile-slot" id="share-mobile"></div>
    </div>
    ${isOwner && quiz.mode !== "adventure" ? assessmentSection(quiz) : ""}`;

  if (isOwner && quiz.mode !== "adventure") bindAssessment(root, quiz);
  wireShare(root);
  placeShare(root, "#share-mobile");
  paintFraming(root);

  // A transcript belongs to the questionnaire, not to a scene: it is read at
  // the top of the page, before the play buttons.
  void mountPlayer(root.querySelector("#quiz-audio"), {
    ownerType: "quiz",
    ownerId: quiz.id,
    language: (quiz.default_language || "").slice(0, 2) || null,
  });

  // Wikis that present this questionnaire. They sit above the play buttons:
  // the questions come from a wiki, so the reading comes first.
  const wikiCard = root.querySelector("#quiz-wikis");
  const wikiList = root.querySelector("#quiz-wikis-list");
  api
    .get(`/api/v1/quizzes/${quiz.id}/wikis`)
    .then((payload) => {
      const wikis = payload.items || [];
      if (!wikiList) return;
      // No wiki, no section: an empty shelf tells a reader the reading they
      // came for does not exist, and its heading promises a chapter anyway.
      if (!wikis.length) return;
      wikiList.innerHTML = wikis
        .map(
          (wiki) => `
          <div class="wiki-quiz-row">
            <div>
              <strong>${escapeHtml(wiki.title)}</strong>
              <p class="muted small">${escapeHtml(wiki.description || "")}</p>
            </div>
            <div class="wiki-quiz-actions">
              <a class="btn btn-sm" data-link href="/wiki/${wiki.id}">${escapeHtml(t("wiki.open"))}</a>
            </div>
          </div>`,
        )
        .join("");
      if (wikiCard) wikiCard.hidden = false;
    })
    .catch(() => {
      if (wikiCard) wikiCard.hidden = true;
    });

  // Bars are sized from data, never from a style attribute (CSP).
  // CSSOM, not a style attribute: the CSP forbids inline styles.
  root.querySelectorAll(".bar-fill[data-width]").forEach((bar) => {
    bar.style.width = `${Math.min(100, Math.max(0, Number(bar.dataset.width) || 0))}%`;
  });

  const selectTab = (key) => {
    root.querySelectorAll("[data-tab]").forEach((tab) => {
      const active = tab.dataset.tab === key;
      tab.classList.toggle("is-active", active);
      tab.setAttribute("aria-selected", String(active));
    });
    const panel = root.querySelector("#tab-panel");
    panel.innerHTML = panelFor(key);
    panel.querySelectorAll(".bar-fill[data-width]").forEach((bar) => {
      bar.style.width = `${Math.min(100, Math.max(0, Number(bar.dataset.width) || 0))}%`;
    });
  };

  const startSession = async (mode, button, playAsHost = false) => {
    button.disabled = true;
    try {
      const result = await api.post(`/api/v1/quizzes/${quiz.id}/sessions`, {
        mode,
        language: currentLanguage(),
        play_as_host: playAsHost,
      });
      const code = result.session.code;
      localStorage.setItem(`ol_ht_${code}`, result.host_token);
      localStorage.setItem(`ol_join_url_${code}`, result.join_url || "");
      if (result.participant) {
        localStorage.setItem(`ol_pt_${code}`, result.participant.token);
        localStorage.setItem(`ol_pid_${code}`, String(result.participant.id));
        localStorage.setItem(`ol_nick_${code}`, result.participant.nickname);
      }
      navigate(mode === "live" ? `/host/${code}` : `/play/${code}`);
    } catch (error) {
      button.disabled = false;
      toast(error.detail || t("common.error"), "error");
    }
  };

  root.addEventListener("click", async (event) => {
    const tab = event.target.closest("[data-tab]");
    if (tab) {
      selectTab(tab.dataset.tab);
      return;
    }
    const jump = event.target.closest("[data-tab-jump]");
    if (jump) {
      selectTab(jump.dataset.tabJump);
      return;
    }
    const restore = event.target.closest("[data-restore]");
    if (restore) {
      const number = restore.dataset.restore;
      const ok = await confirmDialog(t("editor.version_restore"), t("editor.version_restore_hint", { n: number }), t("editor.version_restore"));
      if (!ok) return;
      restore.disabled = true;
      try {
        await api.post(`/api/v1/quizzes/${quiz.id}/versions/${number}/restore`);
        toast(t("editor.version_restored", { n: number }), "success");
        navigate(`/quizzes/${quiz.id}?tab=versions`, { replace: true });
      } catch (error) {
        restore.disabled = false;
        toast(error.detail || t("common.error"), "error");
      }
      return;
    }

    const button = event.target.closest("[data-act]");
    if (!button) return;
    const action = button.dataset.act;

    if (action === "solo" || action === "live" || action === "live-play") {
      const mode = action === "solo" ? "solo" : "live";
      await startSession(mode, button, action === "live-play");
      return;
    }
    if (action === "duplicate") {
      button.disabled = true;
      const copy = await api.post(`/api/v1/quizzes/${quiz.id}/duplicate`).catch((error) => {
        toast(error.detail || t("common.error"), "error");
        button.disabled = false;
        return null;
      });
      if (copy) navigate(`/quizzes/${copy.id}/edit`);
      return;
    }
    if (action === "publish" || action === "retire") {
      button.disabled = true;
      try {
        const result =
          action === "publish"
            ? await api.post(`/api/v1/quizzes/${quiz.id}/publish`, { note: "" })
            : await api.post(`/api/v1/quizzes/${quiz.id}/visibility`, { visibility: "private" });
        if (action === "publish" && result.requires_moderation) toast(t("editor.publish_pending"), "success");
        else toast(action === "publish" ? t("quiz.published") : t("quiz.retired"), "success");
        navigate(`/quizzes/${quiz.id}`, { replace: true });
      } catch (error) {
        button.disabled = false;
        toast(error.detail || t("common.error"), "error");
      }
      return;
    }
    if (action === "ai-legal" || action === "ai-answers" || action === "ai-apply") {
      button.disabled = true;
      try {
        if (action === "ai-apply") {
          const result = await api.post(`/api/v1/quizzes/${quiz.id}/ai/apply-answers`);
          toast(t("editor.ai_applied", { n: result.applied }), "success");
        } else {
          const path = action === "ai-legal" ? "review-legal" : "review-answers";
          const review = await api.post(`/api/v1/quizzes/${quiz.id}/ai/${path}`);
          toast(
            review.status === "blocked" || review.status === "flagged"
              ? t("quiz.review_attention")
              : t("quiz.review_done"),
            review.status === "blocked" ? "error" : "success",
          );
        }
        navigate(`/quizzes/${quiz.id}?tab=reviews`, { replace: true });
      } catch (error) {
        button.disabled = false;
        toast(error.detail || t("common.error"), "error");
      }
      return;
    }
    if (action === "delete") {
      const confirmed = await confirmDialog(t("dash.delete_title"), t("dash.delete_body"), t("action.delete"));
      if (!confirmed) return;
      await api.del(`/api/v1/quizzes/${quiz.id}`);
      toast(t("dash.deleted"), "success");
      navigate("/dashboard");
    }
  });

  return root;
}

function statCard(label, value, hint) {
  return `
    <div class="stat-card">
      <span class="stat-value">${value}</span>
      <span class="stat-label">${label}</span>
      <span class="stat-hint small-note">${hint}</span>
    </div>`;
}
