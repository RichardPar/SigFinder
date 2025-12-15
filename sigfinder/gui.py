"""GUI: simple window with 4 placeholder buttons and a map showing current GPS position.

This uses pywebview to render an HTML page with Leaflet map and four buttons.
The Python side periodically calls JS `update_marker(lat, lon)` to move the map marker.
"""
import threading
import time
import tempfile
import os
# do not import webview at module import time; some backends (Qt) import this module
# to access the HTML templates even when `pywebview` is not installed. Import `webview`
# lazily inside `start_gui()` so the module can be imported by the Qt GUI without
# requiring the `pywebview` dependency to be present.

HTML_TEMPLATE = """
<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SigFinder Map</title>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <style>
      body { margin:0; padding:0; font-family: sans-serif; background: #f0f0f0; }
      /* Map fills entire viewport */
      #map { width: 100%; height: 100vh; min-height: 320px; background: #aad3df; }
    </style>
    <script>
      // Debug helper removed - map is working
      
      // Initialize map when everything is loaded
      window.addEventListener('load', function() {
        console.log('=== Window load event fired ===');
        console.log('Leaflet available:', typeof L);
        
        // Now initialize the map
        initializeMap();
      });
      
      function initializeMap() {
        console.log('sigfinder: initializing map');
        const mapDiv = document.getElementById('map');
        console.log('sigfinder: map div dimensions:', mapDiv ? mapDiv.offsetWidth + 'x' + mapDiv.offsetHeight : 'N/A');
        
        try {
          window.map = L.map('map').setView([52.39, 0.11], 13);
          console.log('sigfinder: map object created successfully');
          
          // Add tile layer
          console.log('sigfinder: adding tile layer');
          const tileLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            maxZoom: 19,
          }).addTo(window.map);
          console.log('sigfinder: tile layer added');
          
          // Force immediate size calculation
          setTimeout(function() {
            console.log('sigfinder: invalidating map size');
            try { 
              window.map.invalidateSize(true); 
              console.log('sigfinder: map size invalidated successfully');
            } catch(e) { 
              console.error('sigfinder: failed to invalidate size:', e);
            }
          }, 100);
        } catch (mapInitErr) {
          console.error('sigfinder: map init error:', mapInitErr);
        }
      }
    </script>
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <script>
      console.log('=== Leaflet script tag executed ===');
      console.log('Leaflet (L) type:', typeof L);
      if (typeof L !== 'undefined') {
        console.log('Leaflet version:', L.version);
      } else {
        console.error('ERROR: Leaflet (L) is undefined after script load!');
      }
      console.log('=== END LEAFLET CHECK ===');
    </script>
  </head>
  <body>
    <script>
      // Small bootstrap: if the main page JS hasn't defined the expected API
      // functions yet, provide queueing stubs so Python can call them early
      // via evaluate_js without causing ReferenceError. The real functions
      // will overwrite these stubs later; we'll flush any queued calls then.
      (function(){
        if (!window._sigfinderQueue) window._sigfinderQueue = [];
        function makeStub(name) {
          if (typeof window[name] === 'undefined') {
            window[name] = function(){ window._sigfinderQueue.push({fn:name, args:Array.prototype.slice.call(arguments)}); };
          }
        }
        makeStub('update_marker');
        makeStub('update_status');
        makeStub('add_signal_sample');
      })();
        </script>
    <div id="map"></div>
    <!-- GPS Info Overlay - bottom left -->
    <div id="gpsOverlay" style="position:absolute;bottom:10px;left:10px;background:rgba(0,0,0,0.75);color:#fff;padding:12px;font-family:monospace;font-size:12px;border-radius:6px;z-index:1000;min-width:280px;backdrop-filter:blur(4px);">
      <div style="font-weight:bold;color:#4af;margin-bottom:8px;border-bottom:1px solid #4af;padding-bottom:4px;">GPS & SYSTEM INFO</div>
      <div id="gpsTime" style="margin-bottom:4px;">Time: --:--:--</div>
      <div id="gpsPos" style="margin-bottom:4px;">Position: No fix</div>
      <div id="gpsSats" style="margin-bottom:4px;">Satellites: --</div>
      <div id="gpsQuality" style="margin-bottom:4px;">Fix Quality: --</div>
      <div id="gpsStatus" style="margin-bottom:4px;">Status: --</div>
      <div id="rssiInfo" style="margin-top:8px;padding-top:8px;border-top:1px solid #666;">RSSI: --</div>
      <div id="localTime" style="margin-top:8px;padding-top:8px;border-top:1px solid #666;color:#8f8;">Local: --:--:--</div>
    </div>
    <!-- Canvas fallback: shown when tiles/leaflet fail; fills same area as #map -->
    <canvas id="fallbackCanvas" style="position:absolute;left:0;top:60px;width:100%;height:calc(100vh - 60px);display:none;z-index:9998;pointer-events:none"></canvas>
    <div id="mapError" style="position:absolute;top:68px;left:8px;z-index:9999;background:rgba(255,255,255,0.9);padding:6px;border-radius:4px;display:none;color:#900;font-weight:bold"></div>

    <script>
      // Map will be initialized by initializeMap() function in the head
      // Store in window.map to make it globally accessible
      window.map = null;
      
      // Fallback canvas drawing helpers
      function showFallbackCanvas(){
        try{
          const c = document.getElementById('fallbackCanvas');
          if(!c) return;
          c.style.display = 'block';
          // ensure canvas sizing matches rendered size
          try { c.width = c.clientWidth; c.height = c.clientHeight; } catch(e) {}
          drawFallback();
        }catch(e){}
      }
      function hideFallbackCanvas(){
        try{ const c = document.getElementById('fallbackCanvas'); if(c) c.style.display = 'none'; }catch(e){}
      }
      function drawFallback(){
        try{
          const c = document.getElementById('fallbackCanvas');
          if(!c) return; const ctx = c.getContext('2d');
          const w = c.width, h = c.height;
          // clear
          ctx.clearRect(0,0,w,h);
          // subtle grid
          ctx.fillStyle = '#fff'; ctx.fillRect(0,0,w,h);
          ctx.strokeStyle = '#eee'; ctx.lineWidth = 1;
          const step = 40;
          for(let x=0;x<w;x+=step){ ctx.beginPath(); ctx.moveTo(x,0); ctx.lineTo(x,h); ctx.stroke(); }
          for(let y=0;y<h;y+=step){ ctx.beginPath(); ctx.moveTo(0,y); ctx.lineTo(w,y); ctx.stroke(); }
          // draw center marker
          ctx.fillStyle = '#4287f5'; ctx.beginPath(); ctx.arc(w/2, h/2, 8, 0, Math.PI*2); ctx.fill();
          ctx.fillStyle = '#000'; ctx.font = '12px sans-serif';
          let txt = 'No tiles - showing fallback';
          if(lastKnownLat !== null && lastKnownLon !== null){ txt = 'Lat: ' + lastKnownLat.toFixed(6) + ', Lon: ' + lastKnownLon.toFixed(6); }
          ctx.fillText(txt, 12, 18);
        }catch(e){ }
      }

      window.marker = null;
      let markerPopupOpened = false;
      let lastStatus = null;
      let RANGE_TRIGGER = -110.0;
      // buffer recent RSSI samples {t: ms_since_epoch, v: value}
      let rssiSamples = [];
      // currently-displayed RSSI (updated once per second to the strongest sample)
      let displayedRSSI = null;
      let lastRSSIUpdateTime = 0;
      // last known map position (updated by update_marker)
      let lastKnownLat = null;
      let lastKnownLon = null;
      // whether we've auto-centered the map once
      let autoCentered = false;
      // whether the user has interacted with the map (pan/zoom/drag)
      let userHasInteracted = false;
      // overlays for bounding boxes and arrow
      let bboxAllRect = null;
      let bboxHighRect = null;
      let arrowLine = null;
      let arrowHead = null;

      function rssiColor(r) {
        // r is expected to be display dBm (negative values), or null
        // Return an HSL color interpolated from red (-120 dBm) to green (-40 dBm).
        if (r === null || typeof r === 'undefined' || isNaN(r)) return '#3388f0';
        const v = parseFloat(r);
        const MIN = -120.0; // worst (left end)
        const MAX = -40.0;  // best (right end)
        // clamp and normalize to 0..1
        let t = (v - MIN) / (MAX - MIN);
        if (t < 0) t = 0;
        if (t > 1) t = 1;
        // Hue 0 = red, 120 = green
        const hue = Math.round(t * 120);
        // return an HSL color string (saturation/lightness chosen for good visibility)
        return 'hsl(' + hue + ',70%,45%)';
      }

      function ensureMarker(latf, lonf, r_val) {
        const color = rssiColor(r_val);
        if (!window.marker) {
          window.marker = L.circleMarker([latf, lonf], {radius:8, color: color, fillColor: color, fillOpacity:0.9}).addTo(window.map);
          window.marker.bindPopup('Current position');
          try { if (!markerPopupOpened) { window.marker.openPopup(); markerPopupOpened = true; } } catch(e) {}
        } else {
          window.marker.setLatLng([latf, lonf]);
          try { window.marker.setStyle({color: color, fillColor: color}); } catch(e) {}
        }
      }

      window.update_marker = function update_marker(lat, lon) {
        console.log('update_marker called with:', lat, lon);
        
        // Store position for GPS overlay
        if (lat !== null && lon !== null) {
          lastKnownLat = lat;
          lastKnownLon = lon;
        }
        
        if (!window.map) {
          console.error('update_marker: map is not initialized');
          return;
        }
        
        // Ensure map is properly sized (critical for Qt WebEngine)
        try {
          window.map.invalidateSize();
        } catch(e) {
          console.error('Failed to invalidate map size:', e);
        }
        
        if (lat === null || lon === null) {
          console.warn('update_marker: received null position; clearing marker');
          if (window.marker) {
            window.map.removeLayer(window.marker);
            window.marker = null;
          }
          return;
        }
        if (!window.marker) {
          console.log('Creating new marker at:', lat, lon);
          window.marker = L.marker([lat, lon]).addTo(window.map);
        } else {
          window.marker.setLatLng([lat, lon]);
        }
        
        // Only auto-center once on first GPS fix (not on every update)
        if (!autoCentered) {
          console.log('Auto-centering map to:', lat, lon);
          window.map.setView([lat, lon], 14);
          autoCentered = true;
        }
      };

      // Update GPS overlay with status information
      function updateGpsOverlay(s) {
        try {
          // GPS Time
          const gpsTimeEl = document.getElementById('gpsTime');
          if (gpsTimeEl) {
            if (s.last_time) {
              // Parse HHMMSS.sss format
              const t = s.last_time;
              if (t.length >= 6) {
                const hh = t.substring(0, 2);
                const mm = t.substring(2, 4);
                const ss = t.substring(4, 6);
                gpsTimeEl.innerHTML = `Time: <span style="color:#4af">${hh}:${mm}:${ss} UTC</span>`;
              } else {
                gpsTimeEl.innerHTML = 'Time: <span style="color:#888">--:--:--</span>';
              }
            } else {
              gpsTimeEl.innerHTML = 'Time: <span style="color:#888">--:--:--</span>';
            }
          }
          
          // Position
          const gpsPosEl = document.getElementById('gpsPos');
          if (gpsPosEl) {
            if (lastKnownLat !== null && lastKnownLon !== null) {
              gpsPosEl.innerHTML = `Position: <span style="color:#4f4">${lastKnownLat.toFixed(6)}, ${lastKnownLon.toFixed(6)}</span>`;
            } else {
              gpsPosEl.innerHTML = 'Position: <span style="color:#f44">No fix</span>';
            }
          }
          
          // Satellites
          const gpsSatsEl = document.getElementById('gpsSats');
          if (gpsSatsEl) {
            const numSats = s.num_sats || 0;
            const color = numSats >= 4 ? '#4f4' : (numSats > 0 ? '#ff4' : '#888');
            gpsSatsEl.innerHTML = `Satellites: <span style="color:${color}">${numSats}</span>`;
          }
          
          // Fix Quality
          const gpsQualityEl = document.getElementById('gpsQuality');
          if (gpsQualityEl) {
            const fq = s.fix_quality || 0;
            let qualityText = 'Invalid';
            let color = '#f44';
            if (fq === 1) { qualityText = 'GPS'; color = '#4f4'; }
            else if (fq === 2) { qualityText = 'DGPS'; color = '#4ff'; }
            else if (fq === 4) { qualityText = 'RTK Fixed'; color = '#4af'; }
            else if (fq === 5) { qualityText = 'RTK Float'; color = '#8af'; }
            else if (fq > 0) { qualityText = 'Fix ' + fq; color = '#ff4'; }
            gpsQualityEl.innerHTML = `Fix Quality: <span style="color:${color}">${qualityText}</span>`;
          }
          
          // RMC Status
          const gpsStatusEl = document.getElementById('gpsStatus');
          if (gpsStatusEl) {
            const rmc = s.rmc_status || 'V';
            const statusText = rmc === 'A' ? 'Active' : 'Void';
            const color = rmc === 'A' ? '#4f4' : '#888';
            const fixCount = s.fix_count || 0;
            gpsStatusEl.innerHTML = `Status: <span style="color:${color}">${statusText}</span> (${fixCount} fixes)`;
          }
          
          // RSSI
          const rssiInfoEl = document.getElementById('rssiInfo');
          if (rssiInfoEl) {
            const r_val = (typeof s.rssi_dbm !== 'undefined' && s.rssi_dbm !== null) ? s.rssi_dbm : null;
            if (r_val !== null) {
              const rssi = parseFloat(r_val);
              let color = '#888';
              // Color code: stronger (closer to 0) is greener
              if (rssi >= -60) color = '#0f0';
              else if (rssi >= -80) color = '#4f4';
              else if (rssi >= -100) color = '#ff4';
              else if (rssi >= -110) color = '#f84';
              else color = '#f44';
              rssiInfoEl.innerHTML = `RSSI: <span style="color:${color};font-weight:bold">${rssi.toFixed(1)} dBm</span>`;
            } else {
              rssiInfoEl.innerHTML = 'RSSI: <span style="color:#888">--</span>';
            }
          }
        } catch (e) {
          console.error('Error updating GPS overlay:', e);
        }
      }
      
      // Update local time clock
      function updateLocalTime() {
        try {
          const localTimeEl = document.getElementById('localTime');
          if (localTimeEl) {
            const now = new Date();
            const hh = String(now.getHours()).padStart(2, '0');
            const mm = String(now.getMinutes()).padStart(2, '0');
            const ss = String(now.getSeconds()).padStart(2, '0');
            localTimeEl.innerHTML = `Local: <span style="color:#8f8">${hh}:${mm}:${ss}</span>`;
          }
        } catch (e) {}
      }
      
      // Update clock every second
      setInterval(updateLocalTime, 1000);
      updateLocalTime(); // Initial update

      // mark user interaction so we stop auto-recentering
      try {
        window.map.on('movestart', function() { userHasInteracted = true; });
        window.map.on('zoomstart', function() { userHasInteracted = true; });
        window.map.on('dragstart', function() { userHasInteracted = true; });
      } catch(e) {}

      // Compute simple geographic centroid from array of {lat,lon}
      function centroid(points) {
        if (!points || !points.length) return null;
        let x = 0, y = 0, z = 0;
        for (const p of points) {
          const lat = p.lat * Math.PI / 180;
          const lon = p.lon * Math.PI / 180;
          x += Math.cos(lat) * Math.cos(lon);
          y += Math.cos(lat) * Math.sin(lon);
          z += Math.sin(lat);
        }
        const cnt = points.length;
        x /= cnt; y /= cnt; z /= cnt;
        const lon = Math.atan2(y, x);
        const hyp = Math.sqrt(x * x + y * y);
        const lat = Math.atan2(z, hyp);
        return {lat: lat * 180 / Math.PI, lon: lon * 180 / Math.PI};
      }

      function bearingBetween(a, b) {
        // returns bearing in degrees from a->b
        const lat1 = a.lat * Math.PI/180, lat2 = b.lat * Math.PI/180;
        const dLon = (b.lon - a.lon) * Math.PI/180;
        const y = Math.sin(dLon) * Math.cos(lat2);
        const x = Math.cos(lat1)*Math.sin(lat2) - Math.sin(lat1)*Math.cos(lat2)*Math.cos(dLon);
        const br = Math.atan2(y, x) * 180/Math.PI;
        return (br + 360) % 360;
      }

      function drawSignalOverlays() {
        // overlays (bounding boxes and directional arrow) removed per user request.
        try {
          if (bboxAllRect) { map.removeLayer(bboxAllRect); bboxAllRect = null; }
          if (bboxHighRect) { map.removeLayer(bboxHighRect); bboxHighRect = null; }
          if (arrowLine) { map.removeLayer(arrowLine); arrowLine = null; }
          if (arrowHead) { map.removeLayer(arrowHead); arrowHead = null; }
        } catch (e) {
          console.error('add_signal_sample error', e, ev);
        }
      }

      // Flush any queued calls that were invoked before the real functions
      // were defined (these were queued by the bootstrap stubs). This is
      // best-effort and will silently ignore failures.
      try {
        if (window._sigfinderQueue && window._sigfinderQueue.length) {
          const q = window._sigfinderQueue.slice();
          window._sigfinderQueue = [];
          for (const it of q) {
            try { if (typeof window[it.fn] === 'function') window[it.fn].apply(null, it.args); } catch(e) {}
          }
        }
      } catch(e) {}
      
      window.update_status = function update_status(obj) {
        try {
          console.log('update_status called with:', obj);
          // Accept either a JSON string or an object
          const s = (typeof obj === 'string') ? JSON.parse(obj) : obj;
          lastStatus = s;
          console.log('update_status parsed to:', s);
          
          // Update GPS overlay
          console.log('Calling updateGpsOverlay...');
          updateGpsOverlay(s);
          console.log('updateGpsOverlay completed');
          
          let text = '';
          // Prefer calibrated dBm if provided, otherwise fall back to raw rssi_max
          const r_val = (typeof s.rssi_dbm !== 'undefined' && s.rssi_dbm !== null) ? s.rssi_dbm : ((typeof s.rssi_max !== 'undefined' && s.rssi_max !== null) ? s.rssi_max : null);
          if (s.fix_quality && s.fix_quality > 0) {
            text = 'Fix: ' + s.fix_quality + ', Sats: ' + s.num_sats + ', Fixes: ' + (s.fix_count || 0);
            if (r_val !== null) {
              try { text += ', RSSI: ' + parseFloat(r_val).toFixed(1) + ' dBm'; } catch(e) {}
            }
            // show max/avg in the status line if available
            if (typeof s.rssi_max_dbm !== 'undefined' && s.rssi_max_dbm !== null) {
              try { text += ', Max: ' + parseFloat(s.rssi_max_dbm).toFixed(1) + ' dBm'; } catch(e) {}
            }
            if (typeof s.rssi_avg_dbm !== 'undefined' && s.rssi_avg_dbm !== null) {
              try { text += ', Avg: ' + parseFloat(s.rssi_avg_dbm).toFixed(1) + ' dBm'; } catch(e) {}
            }
          } else {
            text = `Waiting for fix - sats: ${s.num_sats || 0}, RMC: ${s.rmc_status || 'V'}, Fixes: ${s.fix_count || 0}`;
            if (r_val !== null) {
              try { text += `, RSSI: ${parseFloat(r_val).toFixed(1)} dBm`; } catch(e) {}
            }
            if (typeof s.rssi_max_dbm !== 'undefined' && s.rssi_max_dbm !== null) {
              try { text += `, Max: ${parseFloat(s.rssi_max_dbm).toFixed(1)} dBm`; } catch(e) {}
            }
            if (typeof s.rssi_avg_dbm !== 'undefined' && s.rssi_avg_dbm !== null) {
              try { text += `, Avg: ${parseFloat(s.rssi_avg_dbm).toFixed(1)} dBm`; } catch(e) {}
            }
          }
          // Status bar removed - no longer needed
          // Also set RSSI in marker popup if present, replacing content cleanly
          try {
            if (window.marker) {
              // build popup content using marker coordinates if available
              let popupLat = null;
              let popupLon = null;
              try {
                const ll = window.marker.getLatLng();
                popupLat = ll.lat; popupLon = ll.lng;
              } catch (e) {
                // ignore; no lat/lon available
              }
              let popupContent = '';
              if (popupLat !== null && popupLon !== null) {
                popupContent = 'Lat: ' + popupLat.toFixed(6) + '&nbsp; Lon: ' + popupLon.toFixed(6);
              }
              // Record the incoming last-sample into the sample buffer for 1s aggregation
              try {
                const now = Date.now();
                if (typeof s.rssi_last_dbm !== 'undefined' && s.rssi_last_dbm !== null && !isNaN(s.rssi_last_dbm)) {
                  rssiSamples.push({t: now, v: parseFloat(s.rssi_last_dbm), lat: lastKnownLat, lon: lastKnownLon});
                }
                // drop samples older than 2s to keep buffer small
                const cutoff = now - 2000;
                while (rssiSamples.length && rssiSamples[0].t < cutoff) rssiSamples.shift();
                // compute strongest (maximum numeric, since values are negative dBm display)
                const recent = rssiSamples.filter(x => x.t >= (now - 1000)).map(x => x.v);
                let strongest = null;
                if (recent.length) strongest = Math.max(...recent);

                // Throttle marker popup & color updates to once per second, showing the strongest in last second
                if (now - lastRSSIUpdateTime >= 1000) {
                  lastRSSIUpdateTime = now;
                  displayedRSSI = strongest;
                }

                // Build popup content using current displayedRSSI (not the raw per-update value)
                if (displayedRSSI !== null) {
                  try { popupContent += (popupContent ? '<br/>' : '') + `RSSI: ${parseFloat(displayedRSSI).toFixed(1)} dBm`; } catch(e) {}
                }
                if (typeof s.rssi_max_dbm !== 'undefined' && s.rssi_max_dbm !== null) {
                  try { popupContent += '<br/>' + `Max RSSI: ${parseFloat(s.rssi_max_dbm).toFixed(1)} dBm`; } catch(e) {}
                }
                if (typeof s.rssi_avg_dbm !== 'undefined' && s.rssi_avg_dbm !== null) {
                  try { popupContent += '<br/>' + `Avg RSSI: ${parseFloat(s.rssi_avg_dbm).toFixed(1)} dBm`; } catch(e) {}
                }
                // update marker colour according to displayedRSSI now
                try {
                  const color = rssiColor(displayedRSSI);
                  window.marker.setStyle({color: color, fillColor: color});
                } catch(e) {}
              } catch (e) {
                // ignore sample/aggregation errors
              }
              if (popupContent) {
                try {
                  window.marker.bindPopup(popupContent);
                  // also update marker colour immediately based on new RSSI
                  try {
                    const color = rssiColor((typeof s.rssi_last_dbm !== 'undefined') ? s.rssi_last_dbm : null);
                    window.marker.setStyle({color: color, fillColor: color});
                  } catch(e) {}
                  // redraw overlays (bbox/arrow) now that we have a new sample
                  try { drawSignalOverlays(); } catch(e) {}
                } catch (e) {
                  // ignore popup binding errors
                }
              }
            }
          } catch (e) {
            // ignore popup update errors
          }
        } catch (e) {
          console.error('update_status error', e);
        }
      };
      
      // Test that functions are properly defined
      console.log('=== Functions defined ===');
      console.log('window.update_marker type:', typeof window.update_marker);
      console.log('window.update_status type:', typeof window.update_status);



      function onBtn(n) {
        try {
          // Button 3: start detection (monitor RSSI)
          if (n === 3) {
            try {
              if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.start_detection === 'function') {
                window.pywebview.api.start_detection(RANGE_TRIGGER);
              } else {
                console.log('start_detection API not available');
              }
            } catch(e) { console.log('onBtn start_detection error', e); }
            return;
          }

          // Button 4: re-centre the map to the last known GPS fix or signal marker
          if (n === 4) {
            try {
              if (isFinite(lastKnownLat) && isFinite(lastKnownLon)) {
                map.setView([lastKnownLat, lastKnownLon], 14);
                try { if (map && typeof map.invalidateSize === 'function') map.invalidateSize(); } catch(e) {}
                return;
              }
            } catch(e) { console.log('center error', e); }

            // Fallback: center to signal marker or generic marker if available
            try {
              let p = null;
              if (typeof signalMarker !== 'undefined' && signalMarker && typeof signalMarker.getLatLng === 'function') {
                p = signalMarker.getLatLng();
              } else if (typeof window.marker !== 'undefined' && window.marker && typeof window.marker.getLatLng === 'function') {
                p = window.marker.getLatLng();
              }
              if (p && isFinite(p.lat) && isFinite(p.lng)) {
                map.setView([p.lat, p.lng], 14);
                try { if (map && typeof map.invalidateSize === 'function') map.invalidateSize(); } catch(e) {}
              } else {
                alert('No GPS fix or signal available to centre to.');
              }
            } catch(e) { console.log('onBtn centre fallback error', e); }
            return;
          }

          // Default: placeholder behavior for other buttons
          alert('Button ' + n + ' pressed (placeholder)');
        } catch(e) {
          console.log('onBtn error', e);
        }
      }

      function onRangeTriggerChange(el) {
        try {
          const v = parseFloat(el.value);
          if (!isNaN(v)) {
            RANGE_TRIGGER = v;
            console.log('Range trigger set to', RANGE_TRIGGER);
          }
        } catch(e) { console.log('onRangeTriggerChange error', e); }
      }

      // Test signal functionality removed

      // RSSI trigger control removed in this build
      // Single current signal marker (no history)
      let signalMarker = null;
      let signalPopupOpened = false;

      function haversineMeters(a, b) {
        const R = 6371000; // meters
        const lat1 = a.lat * Math.PI/180, lat2 = b.lat * Math.PI/180;
        const dLat = lat2 - lat1;
        const dLon = (b.lon - a.lon) * Math.PI/180;
        const aa = Math.sin(dLat/2)*Math.sin(dLat/2) + Math.cos(lat1)*Math.cos(lat2)*Math.sin(dLon/2)*Math.sin(dLon/2);
        const c = 2 * Math.atan2(Math.sqrt(aa), Math.sqrt(1-aa));
        return R * c;
      }

      function add_signal_sample(ev) {
        try {
          if (!ev) return;
          const lat = parseFloat(ev.lat);
          const lon = parseFloat(ev.lon);
          const r = (typeof ev.rssi !== 'undefined' && ev.rssi !== null) ? parseFloat(ev.rssi) : null;
          if (!isFinite(lat) || !isFinite(lon)) return;
          const pt = {lat: lat, lon: lon};
          // Create or update a single current signal marker (no history)
          try {
            const color = rssiColor(r);
            if (!signalMarker) {
              signalMarker = L.circleMarker([lat, lon], {radius:6, color: color, fillColor: color, fillOpacity:0.9}).addTo(map);
              try { signalMarker.bindPopup(`Signal ${ev.time || ''}<br/>RSSI: ${r !== null ? r.toFixed(1) : 'n/a'} dBm`); if (!signalPopupOpened) { signalMarker.openPopup(); signalPopupOpened = true; } } catch(e) {}
            } else {
              try { signalMarker.setLatLng([lat, lon]); } catch(e) {}
              try { signalMarker.setStyle({color: color, fillColor: color}); } catch(e) {}
              try { signalMarker.bindPopup(`Signal ${ev.time || ''}<br/>RSSI: ${r !== null ? r.toFixed(1) : 'n/a'} dBm`); } catch(e) {}
            }
          } catch(e) {}
          // No historical signals or overlay layer control (per user request)
        } catch(e) {
          console.error('add_signal_sample error', e, ev);
        }
      }
      
    </script>
  </body>
</html>
"""


HTML_GRAPH_TEMPLATE = """
<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <title>RSSI Graph</title>
    <style>
      body { margin:0; padding:8px; font-family: sans-serif; background:#fff }
      #title { font-weight: bold; margin-bottom:8px }
      #rssiCanvas { width:100%; height:300px; border:1px solid #ccc; }
    </style>
  </head>
  <body>
    <div id="title">RSSI (dBm)</div>
    <canvas id="rssiCanvas"></canvas>
    <script>
      const canvas = document.getElementById('rssiCanvas');
      const ctx = canvas.getContext('2d');
      let data = [];
      const MAX_POINTS = 200;
      const SAMPLE_INTERVAL = 0.2; // seconds between samples (5 Hz)
      
      function resize() {
        canvas.width = canvas.clientWidth;
        canvas.height = canvas.clientHeight;
        draw();
      }
      window.addEventListener('resize', resize);
      resize();

      function update_rssi_graph(v) {
        // v may be null
        const timestamp = Date.now() / 1000; // seconds
        if (v === null || typeof v === 'undefined') {
          data.push({t: timestamp, v: null});
        } else {
          data.push({t: timestamp, v: parseFloat(v)});
        }
        if (data.length > MAX_POINTS) data = data.slice(data.length - MAX_POINTS);
        draw();
      }

      function draw() {
        const w = canvas.width, h = canvas.height;
        ctx.clearRect(0,0,w,h);
        // background
        ctx.fillStyle = '#fafafa'; ctx.fillRect(0,0,w,h);

          // prepare numeric values and autoscale (smoothed)
          const vals = data.filter(x => x.v !== null && !isNaN(x.v)).map(x => x.v);
          // defaults
          let min = -120, max = 0;
          // compute immediate min/max from available values
          if (vals.length) {
            const vmin = Math.min(...vals);
            const vmax = Math.max(...vals);
            // add padding around data
            const pad = Math.max(1, Math.round((vmax - vmin) * 0.15));
            min = Math.floor(vmin) - pad;
            max = Math.ceil(vmax) + pad;
            if (max === min) { max = min + 1; }
          }
          // initialize smoothed scale values if not present
          if (typeof window._scaleMin === 'undefined') window._scaleMin = min;
          if (typeof window._scaleMax === 'undefined') window._scaleMax = max;
          // smooth transition to new target scale to avoid jarring jumps
          const SMOOTH = 0.15; // 0..1, higher = faster response
          window._scaleMin = window._scaleMin * (1 - SMOOTH) + min * SMOOTH;
          window._scaleMax = window._scaleMax * (1 - SMOOTH) + max * SMOOTH;
          // ensure scaleMin < scaleMax
          if (window._scaleMax <= window._scaleMin) {
            window._scaleMax = window._scaleMin + 1;
          }
          // use smoothed values for drawing
          const smin = window._scaleMin;
          const smax = window._scaleMax;

        // draw horizontal grid lines and Y labels
        ctx.strokeStyle = '#eee'; ctx.lineWidth = 1; ctx.fillStyle = '#666'; ctx.font='12px sans-serif';
        const rows = 4;
        for (let y=0; y<=rows; y++) {
          const yy = Math.round(h * y / rows);
          ctx.beginPath(); ctx.moveTo(0, yy); ctx.lineTo(w, yy); ctx.stroke();
          const val = (smax - (smax - smin) * y / rows).toFixed(0);
          ctx.fillText(val + ' dBm', 6, yy - 4);
        }
        
        // Calculate time range for X axis
        const points = data.length;
        if (points > 1) {
          const tMin = data[0].t;
          const tMax = data[points - 1].t;
          const timeSpan = tMax - tMin;
          
          // Draw X axis time labels (seconds)
          ctx.fillStyle = '#666';
          ctx.font = '11px sans-serif';
          const numXLabels = 5;
          for (let i = 0; i <= numXLabels; i++) {
            const x = Math.round(i * w / numXLabels);
            const t = tMin + (timeSpan * i / numXLabels);
            const relativeSeconds = (t - tMax).toFixed(0); // seconds relative to now (negative)
            ctx.fillText(relativeSeconds + 's', x + 2, h - 4);
          }
        }

        // draw the line using actual number of points
        ctx.strokeStyle = '#4287f5'; ctx.lineWidth = 2; ctx.beginPath();
        for (let i=0;i<points;i++) {
          const x = Math.round(i * w / Math.max(1, points-1));
          const v = data[i].v;
          if (v === null || isNaN(v)) {
            ctx.moveTo(x, h);
            continue;
          }
          const y = h - Math.round((v - smin) / (smax - smin) * h);
          if (i===0) ctx.moveTo(x,y); else ctx.lineTo(x,y);
        }
        ctx.stroke();

        // draw current value (last numeric)
        if (vals.length) {
          const cur = vals[vals.length-1];
          ctx.fillStyle = '#000'; ctx.font='14px sans-serif';
          ctx.fillText(cur.toFixed(1) + ' dBm', 8, 18);
        } else {
          ctx.fillStyle = '#000'; ctx.font='14px sans-serif';
          ctx.fillText('no data', 8, 18);
        }
      }
    </script>
  </body>
</html>
"""




# No separate log window — logs remain on console


def _write_html(tmpdir: str) -> str:
    path = os.path.join(tmpdir, 'sigfinder_map.html')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(HTML_TEMPLATE)
    return path


def start_gui(get_position_callable, get_status_callable=None, get_signal_events_callable=None, initial_range_default=-110.0, initial_map_center=None, initial_map_zoom=None, width=900, height=600, config_save_callback=None):
  """Start GUI. `get_position_callable` should be a zero-arg function returning (lat, lon).
  `initial_range_default` sets the initial JS `RANGE_TRIGGER` value shown in the UI."""
  # Import pywebview lazily so the module can be imported by other backends
  # (e.g. the Qt GUI) without requiring pywebview to be installed.
  try:
    import webview
  except Exception as e:
    print('pywebview (webview) is not installed; webview GUI unavailable:', e)
    raise

  tmpdir = tempfile.mkdtemp(prefix='sigfinder_map_')
  map_path = _write_html(tmpdir)
  map_url = 'file://' + map_path

  # We will expose a small API object to the map window so map buttons can
  # request actions in the RSSI window.
  class _GuiApi:
      pass

  _api = _GuiApi()
  # create the map window and attach the Python JS api so the page can call back into Python
  # Enable webview devtools when running in debug mode from main
  try:
    import sigfinder.main as _main
    _debug_flag = bool(getattr(_main, 'DEBUG', False))
  except Exception:
    _debug_flag = False
  map_window = webview.create_window('SigFinder Map', map_url, width=width, height=height, js_api=_api)
  try:
    if _debug_flag:
      try:
        map_window.show_devtools()
      except Exception:
        # some pywebview backends expose different devtools APIs; ignore if unavailable
        pass
  except Exception:
    pass
  # Create a second window for RSSI graph
  graph_path = _write_html(tmpdir)  # temporarily write same name; overwrite next
  # write graph HTML to a different file
  graph_path = os.path.join(tmpdir, 'sigfinder_rssi.html')
  with open(graph_path, 'w', encoding='utf-8') as f:
    f.write(HTML_GRAPH_TEMPLATE)
  graph_url = 'file://' + graph_path
  graph_window = webview.create_window('RSSI Graph', graph_url, width=600, height=360)
  try:
    _api.set_graph_window(graph_window)
  except Exception:
    pass
  

  # prepare JS used to initialize the Range trigger input on the page and optional map view.
  js_init_parts = []
  js_init_parts.append(f"try{{var el=document.getElementById('range_trigger'); if(el) el.value = {float(initial_range_default)}; RANGE_TRIGGER = {float(initial_range_default)};}}catch(e){{console.log('range init error', e);}}")
  # If initial map center/zoom provided, set the map view on load
  try:
    if initial_map_center and isinstance(initial_map_center, (list, tuple)) and len(initial_map_center) == 2:
      latc = float(initial_map_center[0]); lonc = float(initial_map_center[1])
      if initial_map_zoom is not None:
        js_init_parts.append(f"try{{ if (typeof map !== 'undefined' && map) map.setView([{latc}, {lonc}], {int(initial_map_zoom)}); }}catch(e){{console.log('map init view error', e);}}")
      else:
        js_init_parts.append(f"try{{ if (typeof map !== 'undefined' && map) map.setView([{latc}, {lonc}], map.getZoom()); }}catch(e){{console.log('map init view error', e);}}")
  except Exception:
    pass
  js_init = "".join(js_init_parts)

  def updater():
    # Runs in a background thread; call evaluate_js to update marker
    # Throttle map/status/event updates to at most once per second to
    # reduce UI load; keep RSSI graph updates at the current rate.
    last_map_update = 0.0
    while True:
      try:
        lat, lon = get_position_callable()
        now = time.time()
        do_map_update = (now - last_map_update) >= 1.0

        # Build JS for marker update
        if lat is None or lon is None:
          js_marker = 'update_marker(null, null)'
        else:
          js_marker = f'update_marker({lat:.8f}, {lon:.8f})'

        # Evaluate JS on the window object at most once per second. If this fails, log and continue.
        if do_map_update:
          try:
            map_window.evaluate_js(js_marker)
          except Exception as e:
            print('gui: evaluate_js (marker) failed:', e)

        # Fetch and send status JSON if available
        if get_status_callable is not None:
          try:
            import json
            st = get_status_callable()
            print('gui: updater got status ->', st, 'pos=', (lat, lon))
            js_status = f'update_status({json.dumps(st)})'
            if do_map_update:
              try:
                map_window.evaluate_js(js_status)
              except Exception as e:
                print('gui: evaluate_js (status) failed:', e)
              # Persist map center and zoom if requested via callback
              if callable(config_save_callback):
                try:
                  # get center as JSON string
                  cen = map_window.evaluate_js("(function(){var c = (typeof map !== 'undefined' && map)?map.getCenter():null; return c?JSON.stringify({lat:c.lat,lon:c.lng}):null;})()")
                except Exception:
                  cen = None
                try:
                  z = map_window.evaluate_js("(function(){return (typeof map !== 'undefined' && map)?map.getZoom():null;})()")
                except Exception:
                  z = None
                try:
                  if cen:
                    import json as _json
                    cobj = _json.loads(cen) if isinstance(cen, str) else cen
                    latp = float(cobj.get('lat')) if cobj and 'lat' in cobj else None
                    lonp = float(cobj.get('lon')) if cobj and 'lon' in cobj else None
                  else:
                    latp, lonp = None, None
                except Exception:
                  latp, lonp = None, None
                try:
                  zp = int(z) if (z is not None and z != 'null') else None
                except Exception:
                  zp = None
                # only persist if changed
                try:
                  if (latp is not None and lonp is not None) and (not hasattr(updater, '_last_saved_map') or updater._last_saved_map != (latp, lonp, zp)):
                    updater._last_saved_map = (latp, lonp, zp)
                    try:
                      cfg = {'map_center': {'lat': latp, 'lon': lonp}}
                      if zp is not None:
                        cfg['map_zoom'] = zp
                      config_save_callback(cfg)
                    except Exception:
                      pass
                except Exception:
                  pass
              # If a config save callback is provided, poll RANGE_TRIGGER from page and persist
              if callable(config_save_callback):
                try:
                  val = map_window.evaluate_js('RANGE_TRIGGER')
                  # normalize returned value from some pywebview versions
                  try:
                    if isinstance(val, str):
                      valn = float(val)
                    else:
                      valn = float(val)
                  except Exception:
                    valn = None
                  if valn is not None:
                    try:
                      # write only when value changed to avoid frequent writes
                      if not hasattr(updater, '_last_saved_range') or updater._last_saved_range != valn:
                        updater._last_saved_range = valn
                        config_save_callback({'range_trigger': float(valn)})
                    except Exception:
                      pass
                except Exception:
                  pass

            # fetch any queued signal events from the backend and forward to map JS
            try:
              if do_map_update and callable(get_signal_events_callable):
                evs = []
                try:
                  evs = get_signal_events_callable()
                except Exception:
                  evs = []
                for e in evs:
                  import json as _json
                  js_ev = f"add_signal_sample({_json.dumps(e)})"
                  try:
                    map_window.evaluate_js(js_ev)
                  except Exception as e:
                    print('gui: evaluate_js (event) failed:', e)
                # Persist last known position when available
                try:
                  if callable(config_save_callback):
                    latp, lonp = None, None
                    try:
                      latp = float(lat) if lat is not None else None
                      lonp = float(lon) if lon is not None else None
                    except Exception:
                      latp, lonp = None, None
                    if latp is not None and lonp is not None:
                      if not hasattr(updater, '_last_saved_pos') or updater._last_saved_pos != (latp, lonp):
                        updater._last_saved_pos = (latp, lonp)
                        try:
                          config_save_callback({'last_position': {'lat': latp, 'lon': lonp}})
                        except Exception:
                          pass
                except Exception:
                  pass
            except Exception:
              pass

            # Update graph window with latest scalar RSSI (dBm)
            try:
              r = st.get('rssi_last_dbm', None)
              import json as _json
              js_graph = f'update_rssi_graph({ _json.dumps(r) })'
              try:
                graph_window.evaluate_js(js_graph)
              except Exception as e:
                print('gui: evaluate_js (graph) failed:', e)
            except Exception:
              pass

            # if we performed the map update, record the time
            if do_map_update:
              last_map_update = now
          except Exception as e:
            print('gui: evaluate_js (status) failed or get_status error:', e)

        time.sleep(0.2)
      except Exception as e:
        print('gui: updater exception, exiting:', e)
        break

  # Start the GUI and only start the updater thread once the GUI is running.
  def _on_started():
    # Start a short thread that waits for the page JS to be ready before
    # performing the one-time JS init and starting the updater thread.
    def _wait_and_start():
      # Wait for the webview window to signal that it has loaded the page.
      ready = False
      try:
        # This blocks until the loaded event is set or timeout occurs
        if map_window.events.loaded.wait(10):
          ready = True
      except Exception:
        ready = False

      if not ready:
        print('gui: warning — page did not signal loaded event within timeout, continuing anyway')

      # run a one-time JS init from GUI thread so window is ready (best-effort)
      try:
        try:
          map_window.evaluate_js(js_init)
        except Exception as e:
          print('gui: initial evaluate_js failed:', e)
      except Exception:
        pass

      # start background updater after GUI has started
      th = threading.Thread(target=updater, daemon=True)
      th.start()

    threading.Thread(target=_wait_and_start, daemon=True).start()

  webview.start(_on_started)


if __name__ == '__main__':
    # quick test: show map with dummy position
    def gp():
        return 51.5074, -0.1278
    start_gui(gp)
