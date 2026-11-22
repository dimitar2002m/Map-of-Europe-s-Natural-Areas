/*
 * Природни зони в Европа – интерактивна карта.
 * Зависимости (зареждат се преди този файл в index.html):
 *   lib/ol.js (OpenLayers), data/zones-geo.js (ZONES_GEOJSON), data/base-geo.js (BASE_LAND_GEOJSON,
 *   BASE_BORDERS_GEOJSON), data/mask-geo.js (EUROPE_MASK_GEOJSON), data/content.js (ZONES, SPECIES),
 *   data/photos.js (PHOTO_CREDITS – по желание)
 *
 * Слоеве на картата (отдолу нагоре):
 *   морето (цветът на фона) – релеф (по желание) – маската (морето извън Европа) –
 *   сивата суша (с Кавказ) – зоните – държавните граници.
 */
(function () {
  'use strict';

  // ---------- Индекси ----------
  var ZONE_BY_ID = {};
  ZONES.forEach(function (z) { ZONE_BY_ID[z.id] = z; });

  var SPECIES_BY_ID = {};
  SPECIES.forEach(function (s) { SPECIES_BY_ID[s.id] = s; });

  function speciesFor(zoneId, type) {
    return SPECIES.filter(function (s) {
      return s.type === type && s.zones.indexOf(zoneId) !== -1;
    });
  }

  // ---------- Помощни функции ----------
  function esc(text) {
    return String(text == null ? '' : text)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function hexToRgba(hex, alpha) {
    var h = hex.replace('#', '');
    var r = parseInt(h.substring(0, 2), 16);
    var g = parseInt(h.substring(2, 4), 16);
    var b = parseInt(h.substring(4, 6), 16);
    return 'rgba(' + r + ',' + g + ',' + b + ',' + alpha + ')';
  }

  function iconFor(sp) {
    return sp.type === 'plant' ? '🌿' : '🐾';
  }

  // ---------- Снимки ----------
  // Ред на търсене за всяка снимка:
  //   1) файлът от img/, записан в PHOTO_CREDITS (от tools/download_photos.py);
  //   2) файлът от полето photo в content.js (ако е посочен);
  //   3) английската Уикипедия по латинското име (нужна е интернет връзка).
  // Ако нищо не се зареди, остава текст „Няма снимка“.
  var photoCache = {};

  function localPhoto(key) {
    var all = (typeof PHOTO_CREDITS !== 'undefined') ? PHOTO_CREDITS : {};
    var entry = all[key];
    return entry && entry.file ? entry : null;
  }

  function wikiImage(title) {
    if (!title) return Promise.resolve(null);
    if (!photoCache[title]) {
      var url = 'https://en.wikipedia.org/w/api.php?action=query&format=json&formatversion=2' +
        '&origin=*&redirects=1&prop=pageimages&piprop=thumbnail&pithumbsize=640' +
        '&titles=' + encodeURIComponent(title);
      photoCache[title] = fetch(url)
        .then(function (r) {
          if (!r.ok) throw new Error('HTTP ' + r.status);
          return r.json();
        })
        .then(function (j) {
          var page = j && j.query && j.query.pages && j.query.pages[0];
          if (!page || page.missing || !page.thumbnail) return null;
          return { src: page.thumbnail.source };
        })
        .catch(function () { return null; });
    }
    return photoCache[title];
  }

  // Зарежда една снимка. Връща Promise с елемента <img>, или отхвърля при грешка.
  function loadImage(src, alt) {
    return new Promise(function (resolve, reject) {
      var img = new Image();
      img.alt = alt;
      img.decoding = 'async';
      img.onload = function () { resolve(img); };
      img.onerror = function () { reject(new Error('няма файл: ' + src)); };
      img.src = src;
    });
  }

  // Пробва адресите по ред. Връща първата заредена снимка като {img, credit} или null.
  function firstLoadable(candidates, alt) {
    function step(i) {
      if (i >= candidates.length) return Promise.resolve(null);
      return loadImage(candidates[i].src, alt).then(function (img) {
        return { img: img, credit: candidates[i].credit || null };
      }, function () {
        return step(i + 1);
      });
    }
    return step(0);
  }

  // key: "species/<id>" или "zone/<id>"; override: полето photo; wikiTitle: заглавие в en.wikipedia
  function findPhoto(key, override, wikiTitle, alt) {
    var candidates = [];
    var local = localPhoto(key);
    if (local) candidates.push({ src: local.file, credit: local });
    if (override) candidates.push({ src: override, credit: null });

    return firstLoadable(candidates, alt).then(function (hit) {
      if (hit) return hit;
      return wikiImage(wikiTitle).then(function (w) {
        return w ? firstLoadable([{ src: w.src, credit: null }], alt) : null;
      });
    });
  }

  // Слага текст в място на снимката (иконата остава, с бележка отдолу)
  function setStatus(box, text) {
    var s = box.querySelector('.ph-status');
    if (!s) {
      s = document.createElement('span');
      s.className = 'ph-status';
      box.appendChild(s);
    }
    s.textContent = text;
  }

  // Ред с авторство и лиценз. c е записът от PHOTO_CREDITS или null (снимка от Уикипедия).
  function creditLineHTML(c) {
    if (!c) {
      return 'Снимката е от Уикипедия (Wikimedia Commons). Авторът и лицензът са на страницата на статията.';
    }
    var parts = [];
    if (c.source) {
      parts.push('<a href="' + esc(c.source) + '" target="_blank" rel="noopener">Wikimedia Commons ↗</a>');
    }
    parts.push('Автор: ' + esc(c.artist || 'виж страницата на файла'));
    if (c.license) {
      parts.push(c.licenseUrl
        ? 'Лиценз: <a href="' + esc(c.licenseUrl) + '" target="_blank" rel="noopener">' + esc(c.license) + ' ↗</a>'
        : 'Лиценз: ' + esc(c.license));
    }
    var line = 'Снимка: ' + parts.join(' · ') + '.';
    if (c.origin === 'bg') line += ' Снимката е от българската Уикипедия – проверете дали е подходяща.';
    return line;
  }

  // ---------- Карта ----------
  var SEA_COLOR = '#d6e6f0';    // морето и всичко извън Европа
  var LAND_COLOR = '#ebebe8';   // сушата извън зоните (неутрално сиво)

  var selectedId = null;
  var hoverId = null;

  var geojson = new ol.format.GeoJSON();
  var READ_OPTS = { dataProjection: 'EPSG:4326', featureProjection: 'EPSG:3857' };

  function vectorLayer(data, style, zIndex) {
    return new ol.layer.Vector({
      source: new ol.source.Vector({ features: geojson.readFeatures(data, READ_OPTS) }),
      style: style,
      zIndex: zIndex
    });
  }

  // Зоните: наситени цветове, леко прозрачни, за да се вижда подложката под тях
  function zoneStyle(feature) {
    var id = feature.get('id');
    var zone = ZONE_BY_ID[id];
    var color = zone ? zone.color : '#cccccc';
    var isSel = id === selectedId;
    var isHov = id === hoverId;
    var alpha = isSel ? 1 : (isHov ? 0.97 : 0.88);
    return new ol.style.Style({
      fill: new ol.style.Fill({ color: hexToRgba(color, alpha) }),
      stroke: new ol.style.Stroke({
        color: isSel ? '#1b1b1b' : 'rgba(30,30,30,0.35)',
        width: isSel ? 2.5 : (isHov ? 1.6 : 0.6)
      })
    });
  }

  var zoneLayer = vectorLayer(ZONES_GEOJSON, zoneStyle, 5);
  var zoneSource = zoneLayer.getSource();

  // Сивата суша извън зоните (Европа, Турция, Кипър, Исландия и Кавказ)
  var landLayer = vectorLayer(BASE_LAND_GEOJSON,
    new ol.style.Style({ fill: new ol.style.Fill({ color: LAND_COLOR }) }), 2);

  // Държавните граници: тънки бели линии над зоните, за да се виждат и върху цветовете
  var bordersLayer = vectorLayer(BASE_BORDERS_GEOJSON,
    new ol.style.Style({ stroke: new ol.style.Stroke({ color: 'rgba(255,255,255,0.9)', width: 0.9 }) }), 6);

  // Маската покрива всичко извън сушата в цвета на морето. Така релефът (ако се включи)
  // се вижда само над Европа, а другите континенти не.
  var maskLayer = vectorLayer(EUROPE_MASK_GEOJSON,
    new ol.style.Style({ fill: new ol.style.Fill({ color: SEA_COLOR }) }), 1);

  // Релеф (по желание): сенчест релеф на Esri, без улици и без надписи. Изисква интернет.
  var reliefLayer = new ol.layer.Tile({
    source: new ol.source.XYZ({
      url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Shaded_Relief/MapServer/tile/{z}/{y}/{x}',
      maxZoom: 13,
      attributions: 'Релеф: © <a href="https://www.esri.com">Esri</a>, USGS, NOAA'
    }),
    visible: false,
    zIndex: 0
  });

  var map = new ol.Map({
    target: 'map',
    layers: [reliefLayer, maskLayer, landLayer, zoneLayer, bordersLayer],
    view: new ol.View({
      center: ol.proj.fromLonLat([18, 50]),
      zoom: 4,
      minZoom: 2,
      maxZoom: 10,
      // Центърът не се пуска далеч извън Европа. Мащабът е свободен, иначе картата не може
      // да се отдалечи достатъчно и южната Европа излиза от кадъра.
      extent: ol.proj.transformExtent([-40, 26, 75, 86], 'EPSG:4326', 'EPSG:3857'),
      constrainOnlyCenter: true
    })
  });

  // Европа от Исландия до Новая Земя и Свалбард; Турция и Кавказ са в кадър
  var EUROPE_EXTENT = ol.proj.transformExtent([-26, 34, 70, 82], 'EPSG:4326', 'EPSG:3857');
  map.updateSize();
  map.getView().fit(EUROPE_EXTENT, { padding: [24, 24, 24, 24] });

  // Подложка: без релеф (по подразбиране) или със сенчест релеф
  var baseButtons = document.querySelectorAll('[data-base]');

  function setBase(mode) {
    var relief = mode === 'relief';
    reliefLayer.setVisible(relief);
    landLayer.setVisible(!relief);
    baseButtons.forEach(function (b) {
      var on = b.getAttribute('data-base') === mode;
      b.classList.toggle('is-active', on);
      b.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
  }

  baseButtons.forEach(function (btn) {
    btn.addEventListener('click', function () {
      setBase(btn.getAttribute('data-base'));
    });
  });
  setBase('none');

  var mapEl = document.getElementById('map');
  var tooltip = document.getElementById('tooltip');

  function zoneAt(pixel) {
    var feature = map.forEachFeatureAtPixel(pixel, function (f) { return f; }, {
      layerFilter: function (layer) { return layer === zoneLayer; }
    });
    return feature ? feature.get('id') : null;
  }

  function hideTooltip() {
    tooltip.hidden = true;
  }

  map.on('pointermove', function (evt) {
    if (evt.dragging) {
      hideTooltip();
      return;
    }
    var id = zoneAt(evt.pixel);
    if (id !== hoverId) {
      hoverId = id;
      zoneLayer.changed();
    }
    mapEl.style.cursor = id ? 'pointer' : '';
    if (id && ZONE_BY_ID[id]) {
      var rect = mapEl.getBoundingClientRect();
      tooltip.textContent = ZONE_BY_ID[id].name;
      tooltip.style.left = (rect.left + evt.pixel[0] + 14) + 'px';
      tooltip.style.top = (rect.top + evt.pixel[1] + 14) + 'px';
      tooltip.hidden = false;
    } else {
      hideTooltip();
    }
  });

  mapEl.addEventListener('mouseleave', function () {
    hoverId = null;
    zoneLayer.changed();
    hideTooltip();
  });

  map.on('singleclick', function (evt) {
    var id = zoneAt(evt.pixel);
    if (id) selectZone(id, { zoom: false });
  });

  function zoomToZone(id) {
    var extent = ol.extent.createEmpty();
    zoneSource.getFeatures().forEach(function (f) {
      if (f.get('id') === id) ol.extent.extend(extent, f.getGeometry().getExtent());
    });
    if (ol.extent.isEmpty(extent)) return;
    map.getView().fit(extent, { padding: [60, 60, 60, 60], duration: 500, maxZoom: 7 });
  }

  // ---------- Адресна лента (#zona=…) ----------
  function setHash(id) {
    try {
      var base = location.pathname + location.search;
      history.replaceState(null, '', id ? base + '#zona=' + id : base);
    } catch (e) { /* във някои браузъри при file:// – без последствия */ }
  }

  // ---------- Панел ----------
  var panel = document.getElementById('panel');

  function creditHTML() {
    return '<div class="credit">' +
      'Граници на зоните: Европейска агенция по околна среда (EEA), биогеографски региони 2016 – от QGIS проекта, обединени в природни зони.<br>' +
      'Суша и държавни граници: Natural Earth (публичен домейн).<br>' +
      'Релеф (по желание): Esri, USGS, NOAA (World Shaded Relief).<br>' +
      'Снимки: от папка img/ или от Wikimedia Commons чрез Уикипедия. Където авторът и лицензът са известни, са написани при снимката.' +
      '</div>';
  }

  function legendHTML() {
    var items = ZONES.map(function (z) {
      return '<li><button type="button" data-zone="' + esc(z.id) + '">' +
        '<span class="sw" style="background:' + esc(z.color) + '"></span>' +
        '<span><b>' + esc(z.name) + '</b><small>' + esc(z.short) + '</small></span>' +
        '</button></li>';
    }).join('');

    return '<h2>Природни зони</h2>' +
      '<p class="hint">Кликнете зона върху картата или от списъка по-долу. Всяка зона показва климата, почвите, растенията и животните ѝ.</p>' +
      '<ul class="legend">' + items + '</ul>' +
      '<div class="note"><b>Бележка.</b> Зоните са както в учебника. Границите са приблизителни – изготвени са от биогеографските региони на EEA, които са в QGIS проекта. ' +
      'Тундрата, лесотундрата и тайгата са разделени по ширина, а лесостепите – по област. Черноморското крайбрежие е в субтропичната зона. ' +
      'Видовете са примерни, а не изчерпателен списък.</div>' +
      creditHTML();
  }

  function cardHTML(sp) {
    return '<button type="button" class="card" data-species="' + esc(sp.id) + '" ' +
      'aria-label="' + esc(sp.name) + ' (' + esc(sp.latin) + ')">' +
      '<span class="photo"></span>' +
      '<span class="card-body"><b>' + esc(sp.name) + '</b><i>' + esc(sp.latin) + '</i></span>' +
      '</button>';
  }

  function speciesSection(title, list) {
    if (!list.length) return '';
    return '<h3>' + esc(title) + ' <span class="count">' + list.length + '</span></h3>' +
      '<div class="grid">' + list.map(cardHTML).join('') + '</div>';
  }

  function zoneHTML(zone) {
    var plants = speciesFor(zone.id, 'plant');
    var animals = speciesFor(zone.id, 'animal');
    var facts = [
      ['Климат', zone.climate],
      ['Почви', zone.soil],
      ['Растителност', zone.vegetation],
      ['Стопанска дейност и опасности', zone.human]
    ].filter(function (f) { return !!f[1]; });

    var html =
      '<button type="button" class="back" data-action="back">← Всички зони</button>' +
      '<div class="banner" style="--zone-color:' + esc(zone.color) + '"></div>' +
      '<div class="banner-credit" hidden></div>' +
      '<h2>' + esc(zone.name) + '</h2>' +
      '<p class="eea">EEA област: ' + esc(zone.eea) + '</p>' +
      (zone.description ? '<p>' + esc(zone.description) + '</p>' : '') +
      '<button type="button" class="btn" data-action="zoom">Покажи зоната на картата</button>';

    if (facts.length) {
      html += '<dl class="facts">' + facts.map(function (f) {
        return '<div><dt>' + esc(f[0]) + '</dt><dd>' + esc(f[1]) + '</dd></div>';
      }).join('') + '</dl>';
    }

    if (zone.fact) {
      html += '<div class="fact-box" style="--zone-color:' + esc(zone.color) + '">' +
        '<b>' + esc(zone.fact_label || 'Знаете ли?') + '</b>' + esc(zone.fact) + '</div>';
    }

    if (!plants.length && !animals.length) {
      html += '<p class="muted">За тази област няма списък с видове.</p>';
    } else {
      html += speciesSection('Растения', plants) + speciesSection('Животни', animals);
    }

    return html + creditHTML();
  }

  // Зарежда снимките в картите на видовете. Докато се търси, пише „зарежда се…“.
  function hydrateCards(root) {
    root.querySelectorAll('[data-species]').forEach(function (card) {
      var sp = SPECIES_BY_ID[card.getAttribute('data-species')];
      var box = card.querySelector('.photo');
      if (!sp || !box) return;
      box.innerHTML = '<span aria-hidden="true">' + iconFor(sp) + '</span><span class="ph-status">зарежда се…</span>';
      findPhoto('species/' + sp.id, sp.photo, sp.latin, sp.name).then(function (hit) {
        if (hit) {
          box.innerHTML = '';
          box.appendChild(hit.img);
        } else {
          setStatus(box, 'няма снимка');
        }
      });
    });
  }

  function renderLegend() {
    selectedId = null;
    zoneLayer.changed();
    setHash(null);
    panel.innerHTML = legendHTML();
    panel.scrollTop = 0;
  }

  function renderZone(id) {
    var zone = ZONE_BY_ID[id];
    panel.innerHTML = zoneHTML(zone);
    panel.scrollTop = 0;
    hydrateCards(panel);

    findPhoto('zone/' + id, null, zone.wiki, zone.name).then(function (hit) {
      if (!hit || selectedId !== id) return;
      var banner = panel.querySelector('.banner');
      if (!banner) return;
      banner.innerHTML = '';
      banner.appendChild(hit.img);
      if (hit.credit) {
        var line = panel.querySelector('.banner-credit');
        if (line) {
          line.innerHTML = creditLineHTML(hit.credit);
          line.hidden = false;
        }
      }
    });
  }

  function selectZone(id, opts) {
    if (!ZONE_BY_ID[id]) return;
    selectedId = id;
    zoneLayer.changed();
    renderZone(id);
    setHash(id);
    if (opts && opts.zoom) zoomToZone(id);
  }

  panel.addEventListener('click', function (e) {
    var t = e.target.closest('[data-zone],[data-species],[data-action]');
    if (!t || !panel.contains(t)) return;

    if (t.hasAttribute('data-zone')) {
      // от легендата – показваме и зоната на картата
      selectZone(t.getAttribute('data-zone'), { zoom: true });
    } else if (t.hasAttribute('data-species')) {
      openSpecies(t.getAttribute('data-species'));
    } else {
      var action = t.getAttribute('data-action');
      if (action === 'back') renderLegend();
      if (action === 'zoom' && selectedId) zoomToZone(selectedId);
    }
  });

  // ---------- Прозорец с вид ----------
  var modal = document.getElementById('modal');
  var modalBody = document.getElementById('modal-body');
  var currentSpecies = null;

  function openSpecies(id) {
    var sp = SPECIES_BY_ID[id];
    if (!sp) return;
    currentSpecies = id;

    var chips = sp.zones.map(function (zid) {
      var z = ZONE_BY_ID[zid];
      if (!z) return '';
      return '<button type="button" class="chip" data-zone="' + esc(zid) + '">' +
        '<span class="sw" style="background:' + esc(z.color) + '"></span>' + esc(z.name) + '</button>';
    }).join('');

    modalBody.innerHTML =
      '<div class="modal-photo"><span aria-hidden="true">' + iconFor(sp) + '</span>' +
        '<span class="ph-status">зарежда се…</span></div>' +
      '<h2 id="modal-title">' + esc(sp.name) + '</h2>' +
      '<p class="latin">' + esc(sp.latin) + '</p>' +
      '<p>' + esc(sp.desc) + '</p>' +
      '<p class="muted" style="margin-bottom:0">Среща се в зоните:</p>' +
      '<div class="chips">' + chips + '</div>' +
      '<div class="links">' +
        '<a href="https://en.wikipedia.org/wiki/' + encodeURIComponent(sp.latin.replace(/ /g, '_')) +
          '" target="_blank" rel="noopener">Статия в английската Уикипедия ↗</a>' +
        '<a href="https://bg.wikipedia.org/w/index.php?search=' + encodeURIComponent(sp.name) +
          '" target="_blank" rel="noopener">Търсене в българската Уикипедия ↗</a>' +
      '</div>' +
      '<div class="credit" id="modal-credit">Търся снимка…</div>';

    modal.hidden = false;
    modal.querySelector('.modal-close').focus();

    findPhoto('species/' + id, sp.photo, sp.latin, sp.name).then(function (hit) {
      if (currentSpecies !== id) return;
      var box = modalBody.querySelector('.modal-photo');
      var credit = modalBody.querySelector('#modal-credit');
      if (!box || !credit) return;
      if (hit) {
        box.innerHTML = '';
        box.appendChild(hit.img);
        credit.innerHTML = creditLineHTML(hit.credit);
      } else {
        box.innerHTML = '<span aria-hidden="true">' + iconFor(sp) + '</span>' +
          '<span class="ph-status">Няма снимка. Нужна е интернет връзка или файл в папка img/.</span>';
        credit.textContent = 'Снимка не е намерена.';
      }
    });
  }

  function closeModal() {
    modal.hidden = true;
    modalBody.innerHTML = '';
    currentSpecies = null;
  }

  modal.addEventListener('click', function (e) {
    if (e.target === modal) {
      closeModal();
      return;
    }
    var t = e.target.closest('[data-zone],[data-action]');
    if (!t) return;
    if (t.getAttribute('data-action') === 'close-modal') {
      closeModal();
    } else if (t.hasAttribute('data-zone')) {
      closeModal();
      selectZone(t.getAttribute('data-zone'), { zoom: true });
    }
  });

  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && !modal.hidden) closeModal();
  });

  // ---------- Старт ----------
  var fromHash = /zona=([a-z_]+)/.exec(location.hash || '');
  if (fromHash && ZONE_BY_ID[fromHash[1]]) {
    selectZone(fromHash[1], { zoom: true });
  } else {
    renderLegend();
  }
})();
