export function replaceRegion(root, selector, replacement) {
  const current = root.querySelector(selector);
  if (current) {
    current.replaceWith(replacement);
  }
}

export function animateRegion(element) {
  if (!element) {
    return;
  }
  element.classList.remove("region-update");
  void element.offsetWidth;
  element.classList.add("region-update");
}

export function activateMotion(root) {
  root.querySelectorAll(".vital-fill").forEach((fill) => fill.classList.add("is-filled"));
}

export function node(tag, className = "", content = null) {
  const element = document.createElement(tag);
  if (className) {
    element.className = className;
  }
  if (Array.isArray(content)) {
    content.forEach((item) => item != null && element.append(item));
  } else if (content instanceof Node) {
    element.append(content);
  } else if (content != null) {
    element.textContent = String(content);
  }
  return element;
}

export function controlButton(label, action, value, active) {
  const button = node("button", "control-button", label);
  button.type = "button";
  button.dataset.action = action;
  button.dataset.value = value;
  button.setAttribute("aria-pressed", String(active));
  return button;
}

export function renderFacts(facts, className) {
  return node(
    "div",
    className,
    facts.map((fact) => node("span", "", `${fact.label}: ${fact.display}`)),
  );
}

export function detailLine(label, value) {
  return node("p", "", [node("strong", "", label), document.createTextNode(value)]);
}

export function renderGauge(gauge, reverse = false) {
  const values = node("span", "bar-value", gauge.display);
  const title = node("span", "bar-label", gauge.label);
  if (gauge.presentation === "value") {
    return node(
      "div",
      `bar-row metric-row tone-${safeToken(gauge.tone)}${reverse ? " reverse" : ""}`,
      reverse ? [values, title] : [title, values],
    );
  }
  const bar = node("div", `vital-bar tone-${safeToken(gauge.tone)}`);
  const fill = node("span", "vital-fill");
  fill.style.setProperty("--fill", `${gauge.fill_percent}%`);
  bar.append(fill);
  return node(
    "div",
    `bar-row${reverse ? " reverse" : ""}`,
    reverse ? [values, bar, title] : [title, bar, values],
  );
}

export function renderStatusGroup(group) {
  const items = group.items || [];
  const content = items.length
    ? node(
        "div",
        "effect-chips",
        items.map((item) =>
          node(
            "span",
            `effect-chip tone-${safeToken(item.tone)}`,
            item.display ? `${item.label} · ${item.display}` : item.label,
          ),
        ),
      )
    : node("p", "effect-empty", group.empty_text || "");
  return node("section", "participant-effect-group", [
    node("h3", "participant-group-label", group.label),
    content,
  ]);
}

export function renderDetailGroups(groups) {
  return node(
    "div",
    "detail-grid",
    groups.map((group) => detailLine(group.label, groupText(group))),
  );
}

export function renderParticipantRecord(participant) {
  const details = node("details", "participant-record");
  details.append(node("summary", "", participant.detail_label));
  details.append(renderDetailGroups(participant.detail_groups || []));
  return details;
}

export function renderSnapshotParticipant(participant) {
  const details = node("details", "participant-details");
  details.append(
    node("summary", "", [
      node("strong", "", participant.label),
      node(
        "span",
        "",
        (participant.gauges || []).map((gauge) => `${gauge.label} ${gauge.display}`).join(" · "),
      ),
    ]),
  );
  const body = node("div", "snapshot-participant-body");
  (participant.gauges || []).forEach((gauge) => body.append(renderGauge(gauge)));
  body.append(renderStatusGroup(participant.status_group));
  body.append(renderDetailGroups(participant.detail_groups || []));
  details.append(body);
  return details;
}

export function safeToken(value) {
  const token = String(value || "neutral").toLowerCase().replace(/[^a-z0-9_-]/g, "");
  return token || "neutral";
}

function groupText(group) {
  const items = group.items || [];
  if (!items.length) {
    return group.empty_text || "";
  }
  return items
    .map((item) => (item.display ? `${item.label} ${item.display}` : item.label))
    .join("、");
}
