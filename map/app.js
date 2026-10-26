/* global L, MAP_DATA */
(function () {
  const data = window.MAP_DATA;
  if (!data) {
    document.getElementById("stats").textContent =
      "Нет data.js — запустите scripts/build_map_data.py";
    return;
  }

  const COLOR = {
    meet_key: "#2ecc71",
    farewell_key: "#8e44ad",
    combat: "#e74c3c",
    ambush: "#e74c3c",
    sea: "#3498db",
    air: "#3498db",
    family: "#f39c12",
    medical: "#e67e22",
    shelter: "#1abc9c",
    travel_start: "#16a085",
    travel_arrive: "#16a085",
    vehicle: "#7f8c8d",
    other: "#95a5a6",
  };

  const byId = {};
  (data.events || []).forEach((e) => {
    byId[e.id] = e;
  });

  const hubById = {};
  (data.hubs.features || []).forEach((f) => {
    hubById[f.properties.id] = f;
  });

  const map = L.map("map", {
    worldCopyJump: true,
    attributionControl: false,
  }).setView([40, -40], 3);
  const mapCfg = window.IGH_MAP_CONFIG || {};
  const appVersion = mapCfg.version || "0.5.0";
  document.title = `Я! Еду! Домой! - карта маршрута - версия ${appVersion}`;
  const wantOsm =
    mapCfg.mode === "online" ||
    /(?:\?|&)tiles=osm(?:&|$)/i.test(location.search) ||
    location.hash === "#osm";

  function addVectorFallback() {
    const el = map.getContainer();
    el.style.background = "#a8c4d4";
    fetch("vendor/world.geojson")
      .then((r) => {
        if (!r.ok) throw new Error("no world");
        return r.json();
      })
      .then((geo) => {
        L.geoJSON(geo, {
          style: {
            fillColor: "#e8e0d0",
            color: "#9a8f7a",
            weight: 0.6,
            fillOpacity: 1,
            opacity: 1,
          },
          interactive: false,
        }).addTo(map);
      })
      .catch(() => {});
  }

  function addOfflineBasemap() {
    const tmpl = mapCfg.tileTemplate || "tiles/{z}/{x}/{y}.jpg";
    const maxNative = mapCfg.maxNativeZoom != null ? mapCfg.maxNativeZoom : 6;
    const local = L.tileLayer(tmpl, {
      maxZoom: Math.max(18, maxNative),
      maxNativeZoom: maxNative,
      minZoom: 1,
      attribution: "",
    });
    local.addTo(map);

    fetch("tiles/manifest.json")
      .then((r) => (r.ok ? r.json() : null))
      .then((mani) => {
        if (!mani) return;
        if (mani.max_native_zoom != null) {
          local.options.maxNativeZoom = mani.max_native_zoom;
        }
      })
      .catch(() => {});

    fetch("tiles/0/0/0.jpg")
      .then((r) => {
        if (!r.ok) throw new Error("no tile");
      })
      .catch(() => {
        map.removeLayer(local);
        addVectorFallback();
      });
  }

  if (wantOsm) {
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 18,
      attribution: "",
    }).addTo(map);
  } else {
    addOfflineBasemap();
  }

  const layers = {
    route: L.layerGroup().addTo(map),
    causal: L.layerGroup().addTo(map),
    hubs: L.layerGroup().addTo(map),
    now: L.layerGroup().addTo(map),
  };

  const dayMax = data.meta.day_max || 1;
  let currentDay = dayMax;
  let syncingTl = false;

  const tlRange = document.getElementById("tl-range");
  tlRange.min = "1";
  tlRange.max = String(dayMax);
  tlRange.value = String(dayMax);

  function eventsOnDay(day) {
    return (data.events || [])
      .filter((e) => e.day === day && bookOk(e.book_id))
      .sort((a, b) => {
        const rank = (e) =>
          (e.importance === "key" ? 0 : e.importance === "major" ? 1 : 2) +
          (e.pov === "protagonist" ? 0 : 10);
        return rank(a) - rank(b) || a.id.localeCompare(b.id);
      });
  }

  function timelineCut() {
    return document.getElementById("tl-cut").checked;
  }

  function dayOk(day) {
    if (!timelineCut()) return true;
    return day != null && day <= currentDay;
  }

  function updateTimelineChrome() {
    const onDay = eventsOnDay(currentDay);
    const hero = onDay.find((e) => e.pov === "protagonist") || onDay[0];
    const label = `День ${currentDay}`;
    document.getElementById("tl-day").textContent = label;
    document.getElementById("tl-bar-label").textContent = label;
    document.getElementById("tl-meta").textContent =
      `из ${dayMax}` + (onDay.length ? ` · ${onDay.length} соб.` : "");
    const calEl = document.getElementById("tl-cal");
    if (calEl) {
      calEl.textContent = hero && hero.calendar_label
        ? hero.calendar_label
        : (hero && hero.spine_location) || "—";
    }
    document.getElementById("tl-title").textContent = hero
      ? hero.title + (hero.place_name ? ` — ${hero.place_name}` : "")
      : "Нет событий в этот день (по фильтрам книг)";
    const kmEl = document.getElementById("tl-km");
    if (kmEl) {
      const done = kmTraveledByDay(currentDay);
      const total =
        data.meta.route_total_km != null
          ? Number(data.meta.route_total_km)
          : kmTraveledByDay(dayMax);
      kmEl.textContent = `Пройдено: ${formatKm(done)} из ${formatKm(total)}`;
    }
    syncingTl = true;
    tlRange.value = String(currentDay);
    syncingTl = false;
    refreshStopsList();
  }

  function formatKm(km) {
    if (km == null || !isFinite(km)) return "—";
    const n = Number(km);
    if (n < 10) return `${n.toFixed(1).replace(/\.0$/, "")} км`;
    if (n < 100) return `${(Math.round(n * 10) / 10).toString().replace(/\.0$/, "")} км`;
    return `${Math.round(n).toLocaleString("ru-RU")} км`;
  }

  function haversineKm(lat1, lon1, lat2, lon2) {
    const R = 6371;
    const toR = Math.PI / 180;
    const dLat = (lat2 - lat1) * toR;
    const dLon = (lon2 - lon1) * toR;
    const a =
      Math.sin(dLat / 2) * Math.sin(dLat / 2) +
      Math.cos(lat1 * toR) *
        Math.cos(lat2 * toR) *
        Math.sin(dLon / 2) *
        Math.sin(dLon / 2);
    return 2 * R * Math.asin(Math.sqrt(a));
  }

  function pathKmFromCoords(coords) {
    let s = 0;
    for (let i = 1; i < (coords || []).length; i++) {
      s += haversineKm(
        coords[i - 1][1],
        coords[i - 1][0],
        coords[i][1],
        coords[i][0]
      );
    }
    return s;
  }

  function segmentKm(feat) {
    const p = (feat && feat.properties) || {};
    if (p.distance_km != null && isFinite(Number(p.distance_km))) {
      return Number(p.distance_km);
    }
    const c = feat && feat.geometry && feat.geometry.coordinates;
    return c && c.length ? pathKmFromCoords(c) : 0;
  }

  function kmTraveledByDay(day) {
    let sum = 0;
    (data.route.features || []).forEach((f) => {
      const p = f.properties || {};
      if (p.to_day != null && p.to_day <= day) sum += segmentKm(f);
    });
    return sum;
  }

  function transportLabel(t) {
    if (t === "air") return "авиа";
    if (t === "sea") return "море";
    if (t === "land_approx") return "напрямую (примерно)";
    return "по дорогам";
  }

  function refreshStopsList() {
    const box = document.getElementById("stops-list");
    if (!box) return;
    const stops = (data.route.properties && data.route.properties.stops) || [];
    const cut = timelineCut();
    box.innerHTML = stops
      .filter(
        (s) =>
          s.day != null &&
          bookOk(s.book_id) &&
          (!cut || s.day <= currentDay)
      )
      .map((s) => {
        const on = s.day === currentDay ? " on" : "";
        const col = cssColor(
          (data.book_colors && data.book_colors[s.book_id]) || "#888"
        );
        const cal = s.calendar_label ? ` · ${escapeHtml(s.calendar_label)}` : "";
        const dayN = s.day | 0;
        return `<button type="button" class="stop-btn${on}" data-day="${dayN}" data-eid="${escapeHtml(s.event_id || "")}"><span class="book-dot" style="background:${col}"></span><span class="sc">Д${dayN}</span>${escapeHtml(trunc(s.title, 36))}${cal}</button>`;
      })
      .join("");
    box.querySelectorAll(".stop-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const d = parseInt(btn.getAttribute("data-day"), 10);
        if (!Number.isFinite(d)) return;
        setDay(d, { open: true, follow: true });
      });
    });
  }

  function zoomForSpanMeters(dist) {
    if (dist < 4000) return 11;
    if (dist < 15000) return 10;
    if (dist < 50000) return 9;
    if (dist < 120000) return 8;
    if (dist < 300000) return 7;
    if (dist < 700000) return 6;
    if (dist < 1500000) return 5;
    if (dist < 3500000) return 4;
    return 3;
  }

  let cameraZoomAnchor = null;

  function setCameraToPoints(pts, opts) {
    opts = opts || {};
    if (!pts.length) return;
    const smooth = opts.smooth !== false;
    if (pts.length === 1) {
      const zWant = opts.zoom != null ? opts.zoom : 9;
      let z = zWant;
      if (opts.hysteresis && cameraZoomAnchor != null) {
        if (Math.abs(z - cameraZoomAnchor) <= 1) z = cameraZoomAnchor;
        else if (z > cameraZoomAnchor) z = cameraZoomAnchor + 1;
        else z = Math.max(z, cameraZoomAnchor - 2);
      }
      cameraZoomAnchor = z;
      map.setView(pts[0], z, { animate: smooth, duration: 0.55 });
      return;
    }
    const b = L.latLngBounds(pts);
    const dist = map.distance(b.getSouthWest(), b.getNorthEast()) || 1;
    let z = opts.zoom != null ? opts.zoom : zoomForSpanMeters(dist);
    if (opts.hysteresis && cameraZoomAnchor != null) {
      // не дёргать: мелкие сдвиги оставляют прежний масштаб; отдаление — быстрее
      if (Math.abs(z - cameraZoomAnchor) <= 1) z = cameraZoomAnchor;
      else if (z > cameraZoomAnchor) z = Math.min(z, cameraZoomAnchor + 1);
      else z = Math.max(z, cameraZoomAnchor - 2);
    }
    cameraZoomAnchor = z;
    map.setView(b.getCenter(), z, { animate: smooth, duration: 0.6 });
  }

  function fitDayCamera(day, opts) {
    opts = opts || {};
    const pts = [];
    for (let d = Math.max(1, day - 1); d <= day; d++) {
      eventsOnDay(d).forEach((e) => {
        if (e.lat != null && e.lon != null) pts.push([e.lat, e.lon]);
      });
    }
    // подмешать концы сегментов маршрута, прибывающих в этот день
    (data.route.features || []).forEach((f) => {
      const p = f.properties || {};
      if (p.to_day !== day && p.from_day !== day) return;
      const c = (f.geometry && f.geometry.coordinates) || [];
      if (c.length) {
        pts.push([c[0][1], c[0][0]]);
        pts.push([c[c.length - 1][1], c[c.length - 1][0]]);
      }
    });
    if (!pts.length) return;
    setCameraToPoints(pts, {
      hysteresis: !!opts.hysteresis,
      smooth: opts.smooth !== false,
    });
  }

  function setDay(day, opts) {
    opts = opts || {};
    const d = Math.max(1, Math.min(dayMax, day | 0));
    if (d === currentDay && !opts.force) {
      updateTimelineChrome();
      return;
    }
    currentDay = d;
    updateTimelineChrome();
    rebuild({ hideArrivingDay: opts.hideArrivingDay });
    if (opts.fitZoom) {
      fitDayCamera(currentDay, { hysteresis: !!opts.hysteresis });
      return;
    }
    const followEl = document.getElementById("tl-follow");
    const wantFollow =
      opts.forceCenter ||
      (opts.follow !== false && followEl && followEl.checked);
    if (wantFollow) {
      fitDayCamera(currentDay, { hysteresis: !!opts.hysteresis });
      if (opts.open !== false && !opts.skipOpen) {
        const onDay = eventsOnDay(currentDay);
        const hero = onDay.find((e) => e.pov === "protagonist") || onDay[0];
        if (hero) {
          const hub = hubById[hero.hub_id];
          if (hub) openHub(hub.properties, hero.id);
        }
      }
    }
  }

  // --- companion filters UI ---
  const companionsBox =
    document.getElementById("companions-body") ||
    document.getElementById("companions-filters");
  (data.companions || []).forEach((c) => {
    const lab = document.createElement("label");
    // по умолчанию включены — полный маршрут виден сразу
    const cid = escapeHtml(String(c.id || ""));
    const cnt = Number(c.event_count) || 0;
    lab.innerHTML = `<input type="checkbox" class="comp-f" data-cid="${cid}" checked /> ${escapeHtml(c.name)} <span class="muted">(${cnt})</span>`;
    companionsBox.appendChild(lab);
  });
  const clearLab = document.createElement("label");
  clearLab.className = "clear-comp";
  clearLab.innerHTML = `<button type="button" id="comp-clear" class="linkish">Сбросить фильтр спутников</button>`;
  companionsBox.appendChild(clearLab);

  function selectedCompanions() {
    return Array.from(document.querySelectorAll(".comp-f:checked")).map((el) =>
      el.getAttribute("data-cid")
    );
  }

  function companionFilterActive() {
    const all = document.querySelectorAll(".comp-f");
    const sel = selectedCompanions();
    // нет галочек или все галочки — без фильтра (весь маршрут)
    if (!sel.length || sel.length === all.length) return false;
    return true;
  }

  function bookOk(bookId) {
    if (bookId === "book01") return document.getElementById("b1").checked;
    if (bookId === "book02") return document.getElementById("b2").checked;
    if (bookId === "book03") return document.getElementById("b3").checked;
    return true;
  }

  function impOk(imp) {
    if (imp === "key") return document.getElementById("imp-key").checked;
    if (imp === "major") return document.getElementById("imp-major").checked;
    return document.getElementById("imp-normal").checked;
  }

  function companionOk(ev) {
    if (!companionFilterActive()) return true;
    const sel = selectedCompanions();
    const ids = ev.character_ids || [];
    return sel.some((cid) => ids.includes(cid));
  }

  function hubEvents(hubProps) {
    return (hubProps.event_ids || [])
      .map((id) => byId[id])
      .filter(Boolean)
      .filter(
        (e) =>
          bookOk(e.book_id) &&
          impOk(e.importance) &&
          companionOk(e) &&
          dayOk(e.day)
      )
      .sort((a, b) => a.day - b.day || a.id.localeCompare(b.id));
  }

  function dayLabel(d) {
    return d != null ? `День ${d}` : "";
  }

  function dayRange(min, max) {
    if (min == null) return "";
    if (min === max) return dayLabel(min);
    return `Дни ${min}–${max}`;
  }

  function cssColor(c) {
    const s = String(c || "");
    return /^#[0-9a-fA-F]{3,8}$/.test(s) ? s : "#888888";
  }

  function escapeHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function trunc(s, n) {
    s = String(s || "");
    return s.length > n ? s.slice(0, n - 1) + "…" : s;
  }

  const PIVOT_LABELS = {
    decision: "решение / развилка",
    route: "смена маршрута",
    weather: "погода",
    supplies: "припасы",
    encounter: "встреча",
    injury: "ранение",
    death: "смерть",
    danger: "опасность",
    companion: "спутник",
    time: "время / срок",
    combat: "бой",
    plan: "план",
    home: "дом / семья",
  };

  function pivotLabel(code) {
    const k = String(code || "").toLowerCase();
    return PIVOT_LABELS[k] || String(code || "");
  }

  function edgesFor(eventId) {
    const edges = data.edges || [];
    return {
      out: edges.filter((e) => e.from === eventId),
      inn: edges.filter((e) => e.to === eventId),
    };
  }

  function renderCausalHtml(ev) {
    const { out, inn } = edgesFor(ev.id);
    if (!out.length && !inn.length) return "";
    const block = (title, hint, list, dir) => {
      if (!list.length) return "";
      const items = list
        .map((e) => {
          const otherId = dir === "out" ? e.to : e.from;
          const otherTitle = dir === "out" ? e.to_title : e.from_title;
          const otherDay = dir === "out" ? e.to_day : e.from_day;
          const gap =
            dir === "out" &&
            ev.day != null &&
            otherDay != null &&
            otherDay - ev.day > 1
              ? ` <span class="gap muted">(через ${otherDay - ev.day - 1} дн. пути — ключевой итог, не следующий календарный день)</span>`
              : "";
          return `<li><button type="button" class="causal-btn" data-go="${escapeHtml(otherId)}"><span class="kind">${escapeHtml(e.kind_label)}</span> ${escapeHtml(dayLabel(otherDay))}: ${escapeHtml(trunc(otherTitle, 42))}${gap}${e.summary ? `<span class="why">${escapeHtml(e.summary)}</span>` : ""}</button></li>`;
        })
        .join("");
      return `<div class="causal-block"><span class="lbl">${title}</span>${hint ? `<p class="hint tiny">${hint}</p>` : ""}<ul class="causal-list">${items}</ul></div>`;
    };
    return (
      `<div class="causal-wrap">` +
      block(
        "Ключевые последствия дальше",
        "Не полный список дней подряд, а сюжетные скачки: что из этого эпизода выросло позже.",
        out,
        "out"
      ) +
      block(
        "Чему это стало следствием",
        "Откуда выросло текущее событие.",
        inn,
        "inn"
      ) +
      `</div>`
    );
  }

  function renderEventHtml(ev) {
    if (!ev) return "<p class='hint'>Нет события</p>";
    const people = (ev.people || []).filter(Boolean);
    const metaParts = [
      ev.calendar_label,
      ev.place_name,
      ev.book_label,
      ev.type_label,
      ev.importance_label,
      ev.pov === "family_ru" ? ev.pov_label : null,
    ].filter(Boolean);
    const pivotsRu = (ev.pivots || []).map(pivotLabel).filter(Boolean);
    const pivots = pivotsRu.length
      ? `<div class="people"><span class="lbl">Смысл главы (метки)</span>${escapeHtml(pivotsRu.join(", "))}</div>`
      : "";
    const peopleLine = people.length
      ? `<div class="people"><span class="lbl">Участники</span>${escapeHtml(people.join(", "))}<span class="hint tiny"> — кто фигурирует в этом эпизоде (не всегда весь состав группы)</span></div>`
      : "";
    const sought = ev.sought
      ? `<div class="sought"><span class="lbl">Зачем / искали</span>${escapeHtml(ev.sought)}</div>`
      : "";
    const outcome = ev.outcome
      ? `<div class="outcome"><span class="lbl">Чем кончилось</span>${escapeHtml(ev.outcome)}</div>`
      : "";
    const prevBtn = ev.prev_id
      ? `<button type="button" class="nav-btn" data-go="${escapeHtml(ev.prev_id)}">← ${escapeHtml(dayLabel(byId[ev.prev_id] && byId[ev.prev_id].day))}: ${escapeHtml(trunc(ev.prev_title, 28))}</button>`
      : "<span class='nav-ph'></span>";
    const nextBtn = ev.next_id
      ? `<button type="button" class="nav-btn" data-go="${escapeHtml(ev.next_id)}">${escapeHtml(dayLabel(byId[ev.next_id] && byId[ev.next_id].day))}: ${escapeHtml(trunc(ev.next_title, 28))} →</button>`
      : "<span class='nav-ph'></span>";
    const summary = ev.summary && ev.summary.trim() ? ev.summary : "";
    return `
      <div class="day-badge">${escapeHtml(dayLabel(ev.day))}</div>
      <h3 class="ev-title">${escapeHtml(ev.title)}</h3>
      <div class="meta">${escapeHtml(metaParts.join(" · "))}</div>
      ${peopleLine}
      ${pivots}
      ${sought}${outcome}
      ${summary ? `<div class="summary">${escapeHtml(summary)}</div>` : ""}
      ${renderCausalHtml(ev)}
      <div class="nav-row">${prevBtn}${nextBtn}</div>
    `;
  }

  function goEvent(id) {
    const ev = byId[id];
    if (!ev) return;
    const hubFeat = hubById[ev.hub_id];
    if (hubFeat) openHub(hubFeat.properties, ev.id);
    else {
      paintPanel(null, ev.id);
      map.panTo([ev.lat, ev.lon], { animate: true });
    }
  }

  function bindNav(root) {
    root.querySelectorAll("[data-go]").forEach((btn) => {
      btn.addEventListener("click", () => goEvent(btn.getAttribute("data-go")));
    });
  }

  function paintPanel(hubProps, selectedId) {
    const hint = document.querySelector("#detail .hint");
    const body = document.getElementById("detail-body");
    hint.hidden = true;
    body.hidden = false;

    if (!hubProps) {
      body.innerHTML = renderEventHtml(byId[selectedId]);
      bindNav(body);
      return;
    }

    const list = hubEvents(hubProps);
    const sel = byId[selectedId] || list[list.length - 1];
    const items = list
      .map((e) => {
        const on = e.id === (sel && sel.id) ? " on" : "";
        return `<li><button type="button" class="hub-ev${on}" data-eid="${escapeHtml(e.id)}"><span class="d">${escapeHtml(dayLabel(e.day))}</span> ${escapeHtml(e.title)}</button></li>`;
      })
      .join("");

    body.innerHTML = `
      <div class="day-badge">${escapeHtml(
        dayRange(
          list.length ? list[0].day : hubProps.day_min,
          list.length ? list[list.length - 1].day : hubProps.day_max
        )
      )}</div>
      <h3>${escapeHtml(hubProps.name)}</h3>
      <div class="meta">${escapeHtml(hubProps.name_map || "")} · ${list.length} событ. — выберите строку</div>
      <ul class="hub-list">${items}</ul>
      <hr class="sep"/>
      <div id="ev-panel">${renderEventHtml(sel)}</div>
    `;
    body.querySelectorAll(".hub-ev").forEach((btn) => {
      btn.addEventListener("click", () => openHub(hubProps, btn.getAttribute("data-eid")));
    });
    bindNav(body);
  }

  function openHub(hubProps, selectedId) {
    const list = hubEvents(hubProps);
    let sid = selectedId;
    if (!sid || !list.some((e) => e.id === sid)) {
      const key = [...list].reverse().find((e) => e.importance === "key");
      sid = (key || list[list.length - 1] || {}).id;
    }
    paintPanel(hubProps, sid);
    const ev = byId[sid];
    if (ev) map.panTo([ev.lat, ev.lon], { animate: true });
    highlightCausalFor(sid);
  }

  function hubIcon(props, evs, dimmed) {
    const hasKey = evs.some((e) => e.importance === "key");
    const onlyFamily = evs.length && evs.every((e) => e.pov === "family_ru");
    const t = (evs.find((e) => e.importance === "key") || evs[evs.length - 1] || {}).type;
    let c = cssColor(COLOR[t] || COLOR.other);
    if (onlyFamily) c = cssColor(COLOR.family);
    const bookCol = cssColor(
      (props.book_colors && props.book_colors[0]) ||
        (data.book_colors && data.book_colors[(props.books || [])[0]]) ||
        "#ffffff"
    );
    const dayTxt =
      props.day_min === props.day_max ? `Д${props.day_min}` : `Д${props.day_min}–${props.day_max}`;
    const opacity = dimmed ? "opacity:0.35" : "";
    return L.divIcon({
      className: "hub-icon-wrap",
      html: `<div class="hub-marker${hasKey ? " hub-key" : ""}" style="--c:${c};--ring:${bookCol};${opacity}"><span class="hub-n">${evs.length}</span><span class="hub-d">${escapeHtml(dayTxt)}</span></div>`,
      iconSize: [48, 40],
      iconAnchor: [24, 20],
    });
  }

  let causalHighlight = null;

  // Пунктир тонкий — клик ловит невидимая широкая «подушка» (как casing у маршрута).
  const CAUSAL_HIT_WEIGHT = 16;

  function causalPopupHtml(edge) {
    const kind = edge.kind_label || edge.kind || "";
    const sum = edge.summary || "";
    return (
      `<div class="causal-popup">` +
      `<div>${escapeHtml(dayLabel(edge.from_day))} ${escapeHtml(edge.from_title || "")}</div>` +
      `<div>→ ${escapeHtml(dayLabel(edge.to_day))} ${escapeHtml(edge.to_title || "")}</div>` +
      (kind ? `<div class="causal-kind"><em>${escapeHtml(kind)}</em></div>` : "") +
      (sum ? `<div class="causal-sum">${escapeHtml(sum)}</div>` : "") +
      `</div>`
    );
  }

  function addCausalLine(target, latlngs, visual, popupHtml) {
    const group = L.layerGroup();
    const hit = L.polyline(latlngs, {
      color: visual.color,
      weight: CAUSAL_HIT_WEIGHT,
      opacity: 0,
      interactive: true,
      className: "causal-hit",
      bubblingMouseEvents: false,
    });
    hit.bindPopup(popupHtml, {
      maxWidth: 420,
      minWidth: 220,
      maxHeight: 280,
      autoPanPadding: [24, 24],
      className: "igh-popup",
    });
    const line = L.polyline(latlngs, {
      color: visual.color,
      weight: visual.weight,
      opacity: visual.opacity,
      dashArray: visual.dashArray,
      interactive: false,
      lineCap: "round",
      lineJoin: "round",
    });
    group.addLayer(hit);
    group.addLayer(line);
    target.addLayer(group);
    return group;
  }

  function highlightCausalFor(eventId) {
    if (causalHighlight) {
      layers.causal.removeLayer(causalHighlight);
      causalHighlight = null;
    }
    if (!document.getElementById("f-causal").checked || !eventId) return;
    const { out, inn } = edgesFor(eventId);
    const all = out.concat(inn);
    if (!all.length) return;
    const group = L.layerGroup();
    all.forEach((edge) => {
      const a = byId[edge.from];
      const b = byId[edge.to];
      if (!a || !b) return;
      addCausalLine(
        group,
        [
          [a.lat, a.lon],
          [b.lat, b.lon],
        ],
        { color: "#e74c3c", weight: 2.5, opacity: 0.85, dashArray: "1 6" },
        causalPopupHtml(edge)
      );
    });
    layers.causal.addLayer(group);
    causalHighlight = group;
  }

  function drawAllCausal() {
    layers.causal.clearLayers();
    causalHighlight = null;
    if (!document.getElementById("f-causal").checked) return;
    // лёгкий фон всех рёбер; ярче — при выборе события
    (data.edges || []).forEach((edge) => {
      const a = byId[edge.from];
      const b = byId[edge.to];
      if (!a || !b) return;
      if (!bookOk(a.book_id) || !bookOk(b.book_id)) return;
      if (!dayOk(a.day) || !dayOk(b.day)) return;
      if (!companionOk(a) && !companionOk(b)) return;
      addCausalLine(
        layers.causal,
        [
          [a.lat, a.lon],
          [b.lat, b.lon],
        ],
        { color: "#c0392b", weight: 1.5, opacity: 0.35, dashArray: "2 8" },
        causalPopupHtml(edge)
      );
    });
  }

  function routeColors(feat, phase) {
    const p = (feat && feat.properties) || {};
    const t = p.transport || "land";
    const marietta = p.vessel === "Мариетта";
    let core;
    if (t === "air") core = { color: "#1a8cff", weight: 3.5, dashArray: "2 8" };
    else if (t === "sea")
      core = {
        color: marietta ? "#0b3d66" : "#0066cc",
        weight: marietta ? 5 : 4,
        dashArray: marietta ? "10 5" : "8 6",
      };
    else if (t === "land_approx")
      core = { color: "#e67e22", weight: 3, dashArray: "4 6" };
    else core = { color: "#d35400", weight: 4.5 }; // суша — яркий оранжевый
    if (phase === "future")
      return {
        casing: { color: "#222", weight: core.weight + 3, opacity: 0.08 },
        core: { ...core, opacity: 0.2 },
      };
    if (phase === "now")
      return {
        casing: { color: "#111", weight: core.weight + 5, opacity: 0.95 },
        core: {
          ...core,
          color: "#ffe566",
          weight: core.weight + 1.5,
          opacity: 1,
        },
      };
    return {
      casing: { color: "#1a1a1a", weight: core.weight + 3.5, opacity: 0.85 },
      core: { ...core, opacity: 0.95 },
    };
  }

  function bindRoutePopup(f, lyr) {
    const fp = f.properties || {};
    const km = segmentKm(f);
    const vessel = fp.vessel
      ? `<br/><em>борт «${escapeHtml(fp.vessel)}»</em>`
      : "";
    lyr.bindPopup(
      `<strong>${escapeHtml(formatKm(km))}</strong>` +
        `<br/>${escapeHtml(dayLabel(fp.from_day))} → ${escapeHtml(dayLabel(fp.to_day))}` +
        `<br/>${escapeHtml(fp.from_title || "")} → ${escapeHtml(fp.to_title || "")}` +
        `<br/><span class="muted">${escapeHtml(transportLabel(fp.transport))}</span>` +
        vessel,
      { maxWidth: 360, className: "igh-popup" }
    );
  }

  function rebuild(opts) {
    opts = opts || {};
    layers.route.clearLayers();
    layers.hubs.clearLayers();
    layers.now.clearLayers();

    if (document.getElementById("f-route").checked && data.route.features.length) {
      const cut = timelineCut();
      data.route.features.forEach((feat) => {
        const p = feat.properties || {};
        const toDay = p.to_day;
        let phase = "past";
        if (cut) {
          if (toDay == null) phase = "past";
          else if (toDay > currentDay) phase = "future";
          else if (toDay === currentDay || p.from_day === currentDay) phase = "now";
          else phase = "past";
        }
        if (cut && phase === "future") return;
        // автоход: сегмент «прибытия» рисуем анимацией, не сразу целиком
        if (opts.hideArrivingDay != null && toDay === opts.hideArrivingDay) return;
        const colors = routeColors(feat, cut ? phase : "past");
        const group = L.layerGroup();
        // обводка + яркое ядро — маршрут читается на любой подложке
        group.addLayer(
          L.geoJSON(feat, {
            style: () => ({
              ...colors.casing,
              lineCap: "round",
              lineJoin: "round",
              interactive: false,
            }),
          })
        );
        group.addLayer(
          L.geoJSON(feat, {
            style: () => ({
              ...colors.core,
              lineCap: "round",
              lineJoin: "round",
              interactive: false,
            }),
          })
        );
        // широкая невидимая полоса для клика (км между точками)
        group.addLayer(
          L.geoJSON(feat, {
            style: () => ({
              color: "#000",
              weight: Math.max(14, (colors.core.weight || 4) + 10),
              opacity: 0,
              interactive: true,
              lineCap: "round",
              lineJoin: "round",
              bubblingMouseEvents: false,
            }),
            onEachFeature: bindRoutePopup,
          })
        );
        if (phase === "now") layers.now.addLayer(group);
        else layers.route.addLayer(group);
      });
    }

    drawAllCausal();

    const showHero = document.getElementById("f-hero").checked;
    const showFamily = document.getElementById("f-family").checked;
    const onDayIds = new Set(eventsOnDay(currentDay).map((e) => e.hub_id));

    data.hubs.features.forEach((feat) => {
      const p = feat.properties;
      let evs = hubEvents(p);
      if (!showHero) evs = evs.filter((e) => e.pov === "family_ru");
      if (!showFamily) evs = evs.filter((e) => e.pov === "protagonist");
      if (!evs.length) return;

      const isNow = onDayIds.has(p.id);
      const m = L.marker([feat.geometry.coordinates[1], feat.geometry.coordinates[0]], {
        icon: hubIcon(
          {
            ...p,
            day_min: evs[0].day,
            day_max: evs[evs.length - 1].day,
          },
          evs,
          false
        ),
        title: p.name,
        zIndexOffset: isNow ? 500 : 0,
      });
      if (isNow) {
        L.circleMarker([feat.geometry.coordinates[1], feat.geometry.coordinates[0]], {
          radius: 18,
          color: "#c9a227",
          weight: 2,
          fill: false,
          opacity: 0.9,
        }).addTo(layers.now);
      }
      m.bindPopup(
        `<strong>${escapeHtml(p.name)}</strong><br/>${escapeHtml(dayRange(evs[0].day, evs[evs.length - 1].day))} · ${evs.length} событ.`
      );
      m.on("click", () => openHub(p));
      layers.hubs.addLayer(m);
    });

    updateTimelineChrome();
  }

  [
    "f-route",
    "f-hero",
    "f-family",
    "f-causal",
    "b1",
    "b2",
    "b3",
    "imp-key",
    "imp-major",
    "imp-normal",
    "tl-cut",
    "tl-follow",
  ].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.addEventListener("change", rebuild);
  });
  document.querySelectorAll(".comp-f").forEach((el) => el.addEventListener("change", rebuild));
  document.getElementById("comp-clear").addEventListener("click", () => {
    // снова все включены = без фильтра
    document.querySelectorAll(".comp-f").forEach((el) => {
      el.checked = true;
    });
    rebuild();
  });

  let tlRaf = 0;
  function onTlInput(el) {
    if (syncingTl) return;
    const v = parseInt(el.value, 10);
    if (tlRaf) cancelAnimationFrame(tlRaf);
    tlRaf = requestAnimationFrame(() => {
      tlRaf = 0;
      setDay(v, { open: false, follow: true });
    });
  }
  function onTlChange(el) {
    if (syncingTl) return;
    setDay(parseInt(el.value, 10), { open: true, follow: true });
  }
  tlRange.addEventListener("input", () => onTlInput(tlRange));
  tlRange.addEventListener("change", () => onTlChange(tlRange));
  let autoplayTimer = null;
  let autoplayRunning = false;
  let autoplayAnimRaf = 0;
  let autoplayAnimLayer = null;

  function autoplaySpeedMs() {
    const v = parseInt(document.getElementById("tl-speed").value, 10) || 3;
    return Math.round(3200 / Math.max(1, v));
  }

  function updateSpeedLabel() {
    const el = document.getElementById("tl-speed");
    const lab = document.getElementById("tl-speed-label");
    if (!el || !lab) return;
    const v = parseInt(el.value, 10) || 3;
    lab.textContent =
      v <= 2 ? "медленно" : v <= 4 ? "норма" : v <= 6 ? "быстро" : "очень быстро";
  }

  function cancelAutoplayAnim() {
    if (autoplayAnimRaf) {
      cancelAnimationFrame(autoplayAnimRaf);
      autoplayAnimRaf = 0;
    }
    if (autoplayAnimLayer) {
      try {
        layers.now.removeLayer(autoplayAnimLayer);
      } catch (_) {
        /* ignore */
      }
      autoplayAnimLayer = null;
    }
  }

  function sliceLatLngsByFraction(latlngs, frac) {
    if (!latlngs.length) return [];
    if (frac <= 0) return [latlngs[0]];
    if (frac >= 1) return latlngs.slice();
    const dist = [0];
    for (let i = 1; i < latlngs.length; i++) {
      dist.push(dist[i - 1] + map.distance(latlngs[i - 1], latlngs[i]));
    }
    const total = dist[dist.length - 1] || 1;
    const target = total * frac;
    const out = [latlngs[0]];
    for (let i = 1; i < latlngs.length; i++) {
      if (dist[i] <= target) {
        out.push(latlngs[i]);
        continue;
      }
      const seg = dist[i] - dist[i - 1];
      const t = seg > 0 ? (target - dist[i - 1]) / seg : 1;
      const a = latlngs[i - 1];
      const b = latlngs[i];
      out.push([a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]);
      break;
    }
    return out;
  }

  function animateRouteFeature(feat, durationMs) {
    return new Promise((resolve) => {
      const coords = (feat.geometry && feat.geometry.coordinates) || [];
      if (coords.length < 2) {
        resolve();
        return;
      }
      const latlngs = coords.map((c) => [c[1], c[0]]);
      const colors = routeColors(feat, "now");
      cancelAutoplayAnim();
      const group = L.layerGroup();
      const casing = L.polyline([], {
        ...colors.casing,
        interactive: false,
        lineCap: "round",
        lineJoin: "round",
      });
      const core = L.polyline([], {
        ...colors.core,
        interactive: false,
        lineCap: "round",
        lineJoin: "round",
      });
      group.addLayer(casing);
      group.addLayer(core);
      layers.now.addLayer(group);
      autoplayAnimLayer = group;
      try {
        setCameraToPoints(latlngs, { hysteresis: true, smooth: true });
      } catch (_) {
        /* ignore */
      }
      const t0 = performance.now();
      const step = (now) => {
        if (!autoplayRunning) {
          cancelAutoplayAnim();
          resolve();
          return;
        }
        const p = Math.min(1, (now - t0) / Math.max(220, durationMs));
        const sliced = sliceLatLngsByFraction(latlngs, p);
        casing.setLatLngs(sliced);
        core.setLatLngs(sliced);
        if (p < 1) {
          autoplayAnimRaf = requestAnimationFrame(step);
        } else {
          autoplayAnimRaf = 0;
          resolve();
        }
      };
      autoplayAnimRaf = requestAnimationFrame(step);
    });
  }

  function stopAutoplay() {
    autoplayRunning = false;
    if (autoplayTimer) {
      clearTimeout(autoplayTimer);
      autoplayTimer = null;
    }
    cancelAutoplayAnim();
    const btn = document.getElementById("tl-play");
    if (btn) {
      btn.textContent = "▶ Автоход";
      btn.setAttribute("aria-pressed", "false");
    }
    rebuild();
  }

  async function tickAutoplay() {
    if (!autoplayRunning) return;
    if (currentDay >= dayMax) {
      stopAutoplay();
      return;
    }
    const cut = document.getElementById("tl-cut");
    if (cut && !cut.checked) cut.checked = true;
    const next = currentDay + 1;
    const arriving = (data.route.features || []).filter(
      (f) => (f.properties || {}).to_day === next
    );
    const base = autoplaySpeedMs();

    setDay(next, {
      open: false,
      follow: false,
      fitZoom: !arriving.length,
      hysteresis: true,
      hideArrivingDay: arriving.length ? next : null,
    });

    if (!arriving.length) {
      fitDayCamera(currentDay, { hysteresis: true });
      autoplayTimer = setTimeout(tickAutoplay, Math.max(260, base * 0.4));
      return;
    }

    for (let i = 0; i < arriving.length; i++) {
      if (!autoplayRunning) return;
      const feat = arriving[i];
      const km = segmentKm(feat);
      const dur = Math.min(4800, Math.max(base * 0.75, base * 0.3 + km * 5));
      await animateRouteFeature(feat, dur);
    }
    if (!autoplayRunning) return;
    cancelAutoplayAnim();
    rebuild();
    fitDayCamera(currentDay, { hysteresis: true });
    autoplayTimer = setTimeout(tickAutoplay, Math.max(160, base * 0.22));
  }

  function startAutoplay() {
    if (autoplayRunning) {
      stopAutoplay();
      return;
    }
    cameraZoomAnchor = null;
    if (currentDay >= dayMax) {
      setDay(1, { open: false, follow: false, fitZoom: true, force: true });
    }
    const cut = document.getElementById("tl-cut");
    if (cut) cut.checked = true;
    autoplayRunning = true;
    const btn = document.getElementById("tl-play");
    if (btn) {
      btn.textContent = "⏸ Стоп";
      btn.setAttribute("aria-pressed", "true");
    }
    autoplayTimer = setTimeout(tickAutoplay, 350);
  }

  document.getElementById("tl-prev").addEventListener("click", () => {
    stopAutoplay();
    cameraZoomAnchor = null;
    setDay(currentDay - 1, { open: true, forceCenter: true, skipOpen: true });
  });
  document.getElementById("tl-next").addEventListener("click", () => {
    stopAutoplay();
    cameraZoomAnchor = null;
    setDay(currentDay + 1, { open: true, forceCenter: true, skipOpen: true });
  });
  document.getElementById("tl-play").addEventListener("click", startAutoplay);
  const tlSpeed = document.getElementById("tl-speed");
  if (tlSpeed) {
    updateSpeedLabel();
    tlSpeed.addEventListener("input", updateSpeedLabel);
  }
  function onTlUserScrub() {
    if (autoplayRunning) stopAutoplay();
  }
  tlRange.addEventListener("pointerdown", onTlUserScrub);

  // старт: весь путь виден (день = max), без авто-открытия карточки
  rebuild();

  const bounds = data.hubs.features.map((f) => [
    f.geometry.coordinates[1],
    f.geometry.coordinates[0],
  ]);
  if (bounds.length) map.fitBounds(bounds, { padding: [40, 40], maxZoom: 6 });

  document.getElementById("stats").textContent =
    `Точек: ${data.meta.hubs} · Событий: ${data.meta.events} · Дней: ${data.meta.day_max}` +
    ` · Связей: ${data.meta.edges}` +
    (data.meta.spine_chapters ? ` · Глав (spine): ${data.meta.spine_chapters}` : "") +
    (data.meta.osrm_routed != null ? ` · По дорогам: ${data.meta.osrm_routed}` : "");

  const quitBtn = document.getElementById("btn-quit");
  const quitHint = document.getElementById("quit-hint");
  if (quitBtn) {
    quitBtn.addEventListener("click", async () => {
      if (quitBtn.disabled) return;
      const ok = window.confirm(
        "Остановить программу и закрыть карту?\n\nФоновый сервер завершится — снова открыть карту можно, запустив IGH.exe."
      );
      if (!ok) return;
      quitBtn.disabled = true;
      quitBtn.textContent = "Останавливаю…";
      let stopped = false;
      try {
        const resp = await fetch("/api/quit", {
          method: "POST",
          headers: { Accept: "application/json" },
          cache: "no-store",
        });
        stopped = resp.ok;
        if (!resp.ok) {
          throw new Error("HTTP " + resp.status);
        }
      } catch (err) {
        // Лаунчер мог оборвать соединение сразу после записи igh.stop.
        stopped = String(err && err.message || "").indexOf("HTTP ") !== 0;
      }
      if (!stopped) {
        quitBtn.disabled = false;
        quitBtn.textContent = "Остановить сервер и выйти";
        if (quitHint) {
          quitHint.hidden = false;
          quitHint.textContent =
            "Выход из браузера доступен при запуске через IGH.exe (не через простой http.server).";
        }
        return;
      }
      if (quitHint) {
        quitHint.hidden = false;
        quitHint.textContent = "Сервер остановлен. Можно закрыть эту вкладку.";
      }
      quitBtn.textContent = "Сервер остановлен";
      try {
        window.close();
      } catch (_) {
        /* браузер часто блокирует close вкладки, открытой не скриптом */
      }
      setTimeout(() => {
        try {
          window.close();
        } catch (_) {
          /* ignore */
        }
        if (quitHint) {
          quitHint.hidden = false;
          quitHint.textContent =
            "Сервер остановлен. Закройте эту вкладку вручную (браузер не дал закрыть её автоматически).";
        }
      }, 400);
    });
  }
})();
