const API_BASE = (window.location.origin === 'null' ? '' : window.location.origin) + '/api';
console.log("SkyTracker Frontend Initializing. API_BASE:", API_BASE);

// Map & UI State
let leafletMap = null;
let cellMarkers = {}; 

// State
let pollingInterval = null;
let lastBurstId = 0;

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    console.log("DOM Content Loaded. Initializing SkyTracker logic...");
    
    setupEventListeners();
    
    // Start Heartbeat polling every 10 seconds to save CPU/Heat
    fetchHeartbeat(); // Initial fetch
    pollingInterval = setInterval(() => {
        console.log("Mission-mode update (30s interval)...");
        fetchHeartbeat();
    }, 30000);
});

function setupEventListeners() {
    const btnStartImsi = document.getElementById('btn-start-imsi');
    const btnStartNode = document.getElementById('btn-start-node');
    const btnStop = document.getElementById('btn-stop');
    const btnUpdate = document.getElementById('btn-update');
    const btnMap = document.getElementById('btn-map');
    const btnCloseMap = document.getElementById('btn-close-map');
    const mapModal = document.getElementById('map-modal');

    if (btnStartImsi) {
        btnStartImsi.addEventListener('click', async () => {
            console.log("Button clicked: Catch IMSIs");
            btnStartImsi.disabled = true;
            try {
                const res = await fetch(`${API_BASE}/start/imsi`, { method: 'POST' });
                const data = await res.json();
                if(res.ok) {
                    showToast(data.message || "IMSI Catcher mode active", "success");
                    fetchHeartbeat();
                } else {
                    showToast(`Error: ${data.detail || "Failed to start IMSI mode"}`, "error");
                    console.error("IMSI start failed:", data);
                }
            } catch (err) {
                showToast("Connection error: Is the server running?", "error");
                console.error("Fetch error:", err);
            } finally {
                btnStartImsi.disabled = false;
            }
        });
    }

    if (btnStartNode) {
        btnStartNode.addEventListener('click', async () => {
            console.log("Button clicked: GSM Node");
            btnStartNode.disabled = true;
            try {
                const res = await fetch(`${API_BASE}/start/node`, { method: 'POST' });
                const data = await res.json();
                if(res.ok) {
                    showToast(data.message || "GSM Node mode active", "success");
                    fetchHeartbeat();
                } else {
                    showToast(`Error: ${data.detail || "Failed to start Node mode"}`, "error");
                    console.error("Node start failed:", data);
                }
            } catch (err) {
                showToast("Connection error: Is the server running?", "error");
                console.error("Fetch error:", err);
            } finally {
                btnStartNode.disabled = false;
            }
        });
    }

    if (btnStop) {
        btnStop.addEventListener('click', async () => {
            btnStop.disabled = true;
            try {
                const res = await fetch(`${API_BASE}/stop`, { method: 'POST' });
                if(res.ok) {
                    showToast("Tracking process stopped", "success");
                    fetchHeartbeat();
                } else {
                    showToast("Failed to stop tracking", "error");
                }
            } catch (err) {
                showToast("Connection error", "error");
            } finally {
                btnStop.disabled = false;
            }
        });
    }

    if (btnUpdate) {
        btnUpdate.addEventListener('click', async () => {
            btnUpdate.disabled = true;
            try {
                const res = await fetch(`${API_BASE}/update-codes`, { method: 'POST' });
                if(res.ok) {
                    showToast("Update task triggered", "success");
                } else {
                    showToast("Failed to trigger update", "error");
                }
            } catch (err) {
                showToast("Connection error", "error");
            } finally {
                setTimeout(() => { btnUpdate.disabled = false; }, 3000);
            }
        });
    }

    if (btnMap && mapModal) {
        btnMap.addEventListener('click', () => {
            mapModal.classList.remove('hidden');
            if (leafletMap) {
                setTimeout(() => { leafletMap.invalidateSize(); }, 200); 
            }
        });
    }

    if (btnCloseMap && mapModal) {
        btnCloseMap.addEventListener('click', () => {
            mapModal.classList.add('hidden');
        });
    }
}

async function fetchHeartbeat() {
    const url = `${API_BASE}/refresh`;
    try {
        const response = await fetch(url);
        if (response.ok) {
            const data = await response.json();
            
            // 1. Update Status
            if (data.status) {
                updateStatusUI(data.status);
                setApiConnected(true);
            }
            
            // 2. Update IMSI Table & Map
            if (data.imsis) {
                renderTable(data.imsis);
                updateMap(data.imsis);
            }
            
            // 3. Update RF Bursts
            if (data.bursts) {
                renderBursts(data.bursts);
            }
            
        } else {
            setApiConnected(false);
        }
    } catch (error) {
        console.warn("Heartbeat failed:", error);
        setApiConnected(false);
    }
}

function setApiConnected(isConnected) {
    const indicator = document.getElementById('api-status');
    if (!indicator) return;

    if (isConnected) {
        indicator.textContent = "Connected";
        indicator.className = "status-indicator connected";
    } else {
        indicator.textContent = "Disconnected";
        indicator.className = "status-indicator disconnected";
        updateStatusUnknown();
    }
}

function updateStatusUI(statusMap) {
    for (const [process, state] of Object.entries(statusMap)) {
        const el = document.getElementById(`status-${process}`);
        if (el) {
            el.textContent = state;
            el.className = `badge badge-${state}`;
        }
    }
}

function updateStatusUnknown() {
    const badges = document.querySelectorAll('.status-list .badge');
    badges.forEach(badge => {
        badge.textContent = "Unknown";
        badge.className = "badge badge-unknown";
    });
}

async function fetchData() {
    // fetchData is now handled via Heartbeat, kept for manual triggers if needed
    try {
        const response = await fetch(`${API_BASE}/data/imsis?limit=50`);
        if (response.ok) {
            const data = await response.json();
            renderTable(data.imsis);
            updateMap(data.imsis);
        }
    } catch (error) {
        console.error("Error fetching data:", error);
    }
}

function renderTable(imsis) {
    const tableBody = document.getElementById('imsi-table-body');
    const metricTotal = document.getElementById('metric-total');
    const metricUnique = document.getElementById('metric-unique');
    
    if (!tableBody) return;

    tableBody.innerHTML = '';
    
    if (!imsis || imsis.length === 0) {
        tableBody.innerHTML = `
            <tr class="empty-row">
                <td colspan="6">No IMSI data captured yet.</td>
            </tr>
        `;
        metricTotal.textContent = "0";
        metricUnique.textContent = "0";
        return;
    }

    const uniqueImsis = new Set();

    imsis.forEach(row => {
        uniqueImsis.add(row.imsi);
        
        const tr = document.createElement('tr');
        
        // Use row elements from sqlite, assuming column names: stamp, imsi, mcc, mnc, operator, description
        tr.innerHTML = `
            <td>${formatDate(row.stamp)}</td>
            <td class="imsi-focus">${escapeHTML(row.imsi || '-')}</td>
            <td>${escapeHTML(row.mcc || '-')}</td>
            <td>${escapeHTML(row.mnc || '-')}</td>
            <td>${escapeHTML(row.operator || '-')}</td>
            <td>${escapeHTML(row.description || '-')}</td>
        `;
        tableBody.appendChild(tr);
    });

    metricTotal.textContent = imsis.length.toString();
    metricUnique.textContent = uniqueImsis.size.toString();
}

function formatDate(isoString) {
    if (!isoString) return '-';
    // try to parse ISO string or just return directly if it's already a formatted string
    try {
        const d = new Date(isoString);
        if (isNaN(d.getTime())) return isoString; // fallback
        return d.toLocaleTimeString() + " " + d.toLocaleDateString();
    } catch {
        return isoString;
    }
}

async function fetchBursts() {
    try {
        const response = await fetch(`${API_BASE}/data/bursts?limit=5`);
        if (response.ok) {
            const data = await response.json();
            renderBursts(data.bursts);
        }
    } catch (error) {
        console.error("Error fetching bursts:", error);
    }
}

function renderBursts(bursts) {
    const feed = document.getElementById('activity-feed');
    if (!feed) return;

    if (!bursts || bursts.length === 0) {
        feed.innerHTML = '<p class="empty-msg">No recent RF activity detected.</p>';
        return;
    }

    feed.innerHTML = '';
    bursts.forEach(burst => {
        const item = document.createElement('div');
        const isNew = burst.id > lastBurstId && lastBurstId !== 0;
        item.className = `activity-item ${isNew ? 'new' : ''}`;
        
        const burstTime = burst.timestamp ? new Date(burst.timestamp).toLocaleTimeString() : 'Unknown';
        
        item.innerHTML = `
            <div class="activity-time">${burstTime}</div>
            <div class="activity-info">Signal Burst @ ${burst.frequency} MHz</div>
            <div class="activity-rssi">${burst.rssi} dBm</div>
        `;
        feed.appendChild(item);
    });

    if (bursts.length > 0) {
        lastBurstId = Math.max(...bursts.map(b => b.id));
    }
}

function escapeHTML(str) {
    if (str === null || str === undefined) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    
    container.appendChild(toast);
    
// Remove after 3 seconds
    setTimeout(() => {
        toast.classList.add('fade-out');
        toast.addEventListener('animationend', () => {
            toast.remove();
        });
    }, 3000);
}

// ----------------------------------------------------
// MAP UI LOGIC
// ----------------------------------------------------

function initMap() {
    // Default location (e.g. Center of India or User's rough location)
    // Prototype set to Hamirpur, Himachal Pradesh
    leafletMap = L.map('map-container').setView([31.6862, 76.5213], 13);

    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
        subdomains: 'abcd',
        maxZoom: 20
    }).addTo(leafletMap);
}

function getDummyCoordinate(mcc, mnc, lac, cell) {
    // Generates a deterministically fake coordinate based on cell ID hash.
    // In production, you would swap this out for an OpenCelliD API fetch!
    let cidBase = parseInt(cell) || 0;
    if (cidBase === 0) return null; // Ignore invalid cells
    
    // offset from Hamirpur, Himachal Pradesh
    let latOffset = (cidBase % 100) * 0.001;
    let lonOffset = ((cidBase / 100) % 100) * -0.001;
    
    return [31.6862 + latOffset, 76.5213 + lonOffset];
}

function updateMap(imsis) {
    if (!leafletMap || !imsis || imsis.length === 0) return;

    // Aggregate by Cell ID
    let cells = {};
    imsis.forEach(row => {
        if (!row.cell || row.cell === 'None') return;
        let cellKey = `${row.mcc}-${row.mnc}-${row.lac}-${row.cell}`;
        
        if (!cells[cellKey]) {
            cells[cellKey] = {
                mcc: row.mcc, mnc: row.mnc, lac: row.lac, cell: row.cell,
                operator: row.operator,
                tmsis: new Set()
            };
        }
        
        // Add the IMSI or TMSI string. If IMSI is null, fallback to tmsi1.
        let ident = row.imsi ? `IMSI: ${row.imsi}` : `TMSI: ${row.tmsi1}`;
        if (ident !== 'TMSI: null' && ident !== 'TMSI: -') {
            cells[cellKey].tmsis.add(ident);
        }
    });

    // Draw markers
    Object.keys(cells).forEach(cellKey => {
        const cData = cells[cellKey];
        
        // Check if marker already exists
        if (!cellMarkers[cellKey]) {
            const coords = getDummyCoordinate(cData.mcc, cData.mnc, cData.lac, cData.cell);
            if (!coords) return;
            
            const marker = L.marker(coords).addTo(leafletMap);
            cellMarkers[cellKey] = { marker, data: cData };
        } else {
            // Update the set of TMSIs
            cellMarkers[cellKey].data.tmsis = new Set([...cellMarkers[cellKey].data.tmsis, ...cData.tmsis]);
        }
        
        // Refresh Popup content
        const mObj = cellMarkers[cellKey];
        const tmsiListHTML = Array.from(mObj.data.tmsis).map(t => `<li>${escapeHTML(t)}</li>`).join('');
        
        const popupContent = `
            <div class="popup-tower-title">${escapeHTML(mObj.data.operator || 'Unknown Network')}</div>
            <div style="margin-bottom: 8px;">
                <strong>Cell ID:</strong> ${mObj.data.cell} <br/>
                <strong>LAC:</strong> ${mObj.data.lac} <br/>
                <strong>Nodes Detected:</strong> ${mObj.data.tmsis.size}
            </div>
            <ul class="popup-tower-list">
                ${tmsiListHTML}
            </ul>
        `;
        
        mObj.marker.bindPopup(popupContent);
    });
}
