// Global state for charts and data
let dashboardData = null;
let selectedTicker = null;
let factorChartInstance = null;
let priceChartInstance = null; // Lightweight Chart instance
let candleSeries = null;       // Candlestick series
let volumeSeries = null;       // Volume histogram series
let selectedPeriod = '1y';     // Default period
let currentEtfTab = 'inflow';
let priceUpdateInterval = null;
let mapColorMode = 'kr';       // Default color mode: 'kr' (KOSPI style) or 'us'
let currentMarketView = 'kr'; // Default active market view: KOSPI
let picksSortKey = 'price';   // Pick list sort: default 현재가 (current price)
let picksSortDir = 'desc';    // 'desc' (high→low) or 'asc'
let headerSwapped = true;     // default: 종목명 big / ticker sub. false: ticker first.
let _detailTicker = '';       // last selection, so the swap toggle can re-apply
let _detailName = '';
let marketMapDataCache = {};  // Quote details cache for instant tooltips
let mapFetchSessionId = 0;    // Fetch session token to prevent race conditions
let elMapTooltip = null;      // Floating tooltip element instance
let sparklineCharts = [];      // Array to keep track of sparkline chart instances

// DOM Elements
const elPipelineTime = document.getElementById('pipeline-time');
const elRefreshBtn = document.getElementById('refresh-btn');
const elMarketIndicators = document.getElementById('market-indicators');
const elUniverseCount = document.getElementById('universe-count');
const elPicksContainer = document.getElementById('picks-container');
const elDetailRank = document.getElementById('detail-rank');
const elDetailTicker = document.getElementById('detail-ticker');
const elDetailName = document.getElementById('detail-name');
const elDetailPrice = document.getElementById('detail-price');
const elDetailChange = document.getElementById('detail-change');
const elDetailTarget = document.getElementById('detail-target');
const elDetailUpside = document.getElementById('detail-upside');
const elDetailAiBrief = document.getElementById('detail-ai-brief');
const elOptionsFlowContent = document.getElementById('options-flow-content');
const elEtfFlowsContainer = document.getElementById('etf-flows-container');
const elMacroClaudeContent = document.getElementById('macro-claude-content');
const elMacroGeminiContent = document.getElementById('macro-gemini-content');
const elCalendarContainer = document.getElementById('calendar-container');

// Default market by local (KST) time: 08:00–20:00 -> KR, otherwise -> US.
function getDefaultMarketView() {
    const h = new Date().getHours();
    return (h >= 8 && h < 20) ? 'kr' : 'us';
}

// Apply a market view: state, color preference, color-toggle label, and the
// active nav tab. Rendering (map + picks) reads currentMarketView afterwards.
function setMarketView(view) {
    currentMarketView = view;
    mapColorMode = view; // KR: red-up / US: green-up
    const colorToggle = document.getElementById('map-color-toggle');
    if (colorToggle) {
        colorToggle.textContent = view === 'kr' ? 'KR 방식 (빨강▲)' : 'US 방식 (초록▲)';
        colorToggle.style.color = view === 'kr' ? '#ef4444' : '#10b981';
    }
    const sub = view === 'kr' ? 'kr-market' : 'us-market';
    document.querySelectorAll('.app-menu-bar .menu-link').forEach(l =>
        l.classList.toggle('active', l.getAttribute('data-subview') === sub));
}

// Toggle between the market dashboard and the embedded option-analytics view
// (vendored option_dashboard repo served at /options/). Iframe src is set lazily
// on first open so the 1MB+ page never loads unless requested.
// `market` selects the inner market tab: 'us' | 'kr_etf' | 'kr_stock'.
function showOptionsView(show, market) {
    const optionsView = document.getElementById('options-view');
    if (!optionsView) return;
    const mainBlocks = [
        document.querySelector('.indicators-section'),
        document.querySelector('.dashboard-workspace'),
        document.querySelector('.bottom-insight-workspace'),
    ];
    if (show) {
        const iframe = document.getElementById('options-iframe');
        if (iframe && !iframe.src) {
            iframe.src = iframe.dataset.src; // lazy first load
            // Style overrides for the embed (repo files stay pristine for git pull):
            // - title at 1.5rem with a slimmer header band (py-4 16px -> 6px)
            // - hide the inner market tabs (redundant: the top menu drives them
            //   programmatically via .click(), which works on hidden elements)
            iframe.addEventListener('load', () => {
                try {
                    const doc = iframe.contentDocument;
                    if (doc && !doc.getElementById('embed-overrides')) {
                        const st = doc.createElement('style');
                        st.id = 'embed-overrides';
                        st.textContent =
                            'h1.text-2xl { font-size: 1.5rem !important; }' +
                            'header.bg-slate-800 { padding-top: 6px !important; padding-bottom: 6px !important; }' +
                            '#market-tabs { display: none !important; }';
                        doc.head.appendChild(st);
                    }
                } catch (e) { /* ignore */ }
            }, { once: true });
        }
        if (iframe && market) {
            // Same-origin iframe: click the matching market tab inside it.
            const applyMarket = () => {
                try {
                    const btn = iframe.contentDocument
                        ?.querySelector(`.market-tab[data-market="${market}"]`);
                    if (btn) btn.click();
                } catch (e) { /* iframe not ready — ignore */ }
            };
            if (iframe.contentDocument?.querySelector('.market-tab')) {
                applyMarket(); // already loaded
            } else {
                iframe.addEventListener('load', applyMarket, { once: true });
            }
        }
        optionsView.style.display = 'flex';
        mainBlocks.forEach(el => { if (el) el.style.display = 'none'; });
    } else {
        optionsView.style.display = 'none';
        mainBlocks.forEach(el => { if (el) el.style.display = ''; });
    }
}

// Toggle the embedded AI Trading Center view (관제 센터 — center/center.html
// served at /center/: bot live status, seasonality stats, ANALYSIS rounds).
// Same lazy-iframe pattern as showOptionsView; no style injection needed
// (the page is our own, already dark-themed).
function showCenterView(show) {
    const centerView = document.getElementById('center-view');
    if (!centerView) return;
    const mainBlocks = [
        document.querySelector('.indicators-section'),
        document.querySelector('.dashboard-workspace'),
        document.querySelector('.bottom-insight-workspace'),
    ];
    if (show) {
        const iframe = document.getElementById('center-iframe');
        if (iframe && !iframe.src) {
            iframe.src = iframe.dataset.src; // lazy first load
        }
        centerView.style.display = 'flex';
        mainBlocks.forEach(el => { if (el) el.style.display = 'none'; });
    } else {
        centerView.style.display = 'none';
    }
}

// Initialize App
document.addEventListener('DOMContentLoaded', () => {
    setMarketView(getDefaultMarketView()); // time-based default before first render
    fetchDashboardData();
    initCandleChart();
    
    // Refresh button event listener
    elRefreshBtn.addEventListener('click', () => {
        elRefreshBtn.disabled = true;
        elRefreshBtn.innerHTML = `<svg class="icon animate-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"/></svg> Refreshing...`;
        fetchDashboardData(true);
    });

    // ETF Tab switcher
    document.querySelectorAll('.etf-tab-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            document.querySelectorAll('.etf-tab-btn').forEach(b => b.classList.remove('active'));
            e.target.classList.add('active');
            currentEtfTab = e.target.getAttribute('data-tab');
            renderEtfFlows();
        });
    });

    // Modal buttons
    document.getElementById('open-settings-btn').addEventListener('click', () => {
        openModal('settings-modal');
        loadKeysForm();
    });

    document.getElementById('open-pipeline-btn').addEventListener('click', () => {
        openModal('pipeline-modal');
        checkPipelineStatus();
    });

    // Save keys
    document.getElementById('save-keys-btn').addEventListener('click', (e) => {
        e.preventDefault();
        saveKeys();
    });

    // Run pipeline
    document.getElementById('run-pipeline-start-btn').addEventListener('click', () => {
        triggerPipeline();
    });

    // KR-only refresh (KIS API when keys are set)
    const krRefreshBtn = document.getElementById('run-kr-refresh-btn');
    if (krRefreshBtn) {
        krRefreshBtn.addEventListener('click', () => triggerPipeline(true));
    }

    // Map Color Toggle
    const colorToggle = document.getElementById('map-color-toggle');
    if (colorToggle) {
        // Initial label/color is set by setMarketView() at init (time-based).
        colorToggle.addEventListener('click', () => {
            if (mapColorMode === 'us') {
                mapColorMode = 'kr';
                colorToggle.textContent = 'KR 방식 (빨강▲)';
                colorToggle.style.color = '#ef4444';
            } else {
                mapColorMode = 'us';
                colorToggle.textContent = 'US 방식 (초록▲)';
                colorToggle.style.color = '#10b981';
            }
            renderMarketMap();
            // Re-render candlestick chart to reflect color preference
            if (selectedTicker) {
                renderTrendChart(selectedTicker);
            }
        });
    }

    // Ticker Search Event Listeners
    const searchInput = document.getElementById('stock-search-input');
    const searchBtn = document.getElementById('stock-search-btn');
    if (searchBtn && searchInput) {
        const handleSearch = () => {
            let query = searchInput.value.trim().toUpperCase();
            if (!query) return;
            // Handle Korean stock code (6 digits)
            if (/^\d{6}$/.test(query)) {
                query = query + '.KS';
            }
            selectStock(query);
        };
        searchBtn.addEventListener('click', handleSearch);
        searchInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') handleSearch();
        });
    }

    // Period buttons click handlers
    document.querySelectorAll('.btn-period').forEach(btn => {
        btn.addEventListener('click', (e) => {
            document.querySelectorAll('.btn-period').forEach(b => b.classList.remove('active'));
            e.target.classList.add('active');
            selectedPeriod = e.target.getAttribute('data-period');
            if (selectedTicker) {
                renderTrendChart(selectedTicker);
            }
        });
    });

    // Chart-header ticker <-> name position swap
    const swapBtn = document.getElementById('header-swap-btn');
    if (swapBtn) {
        swapBtn.classList.toggle('active', headerSwapped); // reflect default state
        swapBtn.addEventListener('click', () => {
            headerSwapped = !headerSwapped;
            swapBtn.classList.toggle('active', headerSwapped);
            setDetailHeader(_detailTicker, _detailName); // re-apply for current selection
        });
    }

    // Pick-list sort buttons (현재가 / 등락률 / 거래대금 / 시총 / 점수)
    document.querySelectorAll('#picks-sort-bar .sort-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const key = btn.getAttribute('data-sort');
            if (picksSortKey === key) {
                picksSortDir = (picksSortDir === 'desc') ? 'asc' : 'desc'; // toggle direction
            } else {
                picksSortKey = key;
                picksSortDir = 'desc';
            }
            document.querySelectorAll('#picks-sort-bar .sort-btn').forEach(b => {
                b.classList.toggle('active', b === btn);
                b.classList.toggle('asc', b === btn && picksSortDir === 'asc');
            });
            renderTopPicks(true); // keep current selection, just re-order
        });
    });

    // Navigation Menu click handlers (Visual indicators)
    document.querySelectorAll('.menu-link').forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            const parent = e.target.closest('.app-menu-bar');
            parent.querySelectorAll('.menu-link').forEach(l => l.classList.remove('active'));
            e.target.classList.add('active');

            // Handle main menus (mock actions or tab switches)
            const view = e.target.getAttribute('data-view');
            const subview = e.target.getAttribute('data-subview');
            // Any menu click leaves the options view unless it IS an options menu
            // (미국ETF / 한국ETF / 한국옵션 share the view, differing by data-market).
            showOptionsView(view === 'options', e.target.getAttribute('data-market'));
            // 관제 센터 view toggles the same way (after showOptionsView so its
            // main-block restore never overrides the center view's hide).
            showCenterView(view === 'center');
            if (view === 'reports') {
                // Focus AI macro analysis
                const macroSection = document.querySelector('.macro-ai-section');
                if (macroSection) macroSection.scrollIntoView({ behavior: 'smooth' });
            } else if (subview === 'calendar') {
                const calSection = document.querySelector('.calendar-section');
                if (calSection) calSection.scrollIntoView({ behavior: 'smooth' });
            } else if (subview === 'kr-market') {
                setMarketView('kr');
                selectedTicker = null;       // drop any US selection
                renderMarketMap();
                renderTopPicks();            // rebuild list + auto-select default (005930.KS)
            } else if (subview === 'us-market') {
                setMarketView('us');
                selectedTicker = null;
                renderMarketMap();
                renderTopPicks();            // rebuild list + auto-select default (AAPL)
            }
        });
    });

    // Handle map resize dynamically
    window.addEventListener('resize', () => {
        if (dashboardData) {
            renderMarketMap();
        }
    });
});


// Fetch main dashboard data
async function fetchDashboardData(isManual = false) {
    try {
        const response = await fetch('/api/dashboard');
        if (!response.ok) throw new Error('Failed to fetch dashboard data');
        
        dashboardData = await response.json();
        renderDashboard(isManual);
    } catch (error) {
        console.error('Error fetching dashboard:', error);
        alert('대시보드 데이터를 가져오는데 실패했습니다. 백엔드가 실행 중인지 확인하세요.');
    } finally {
        if (isManual) {
            elRefreshBtn.disabled = false;
            elRefreshBtn.innerHTML = `<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"/></svg> Refresh`;
        }
    }
}

// Render Dashboard components
function renderDashboard(isManual = false) {
    // 1. Pipeline Time
    if (dashboardData.generated_at) {
        const date = new Date(dashboardData.generated_at);
        elPipelineTime.textContent = date.toLocaleString('ko-KR');
    }

    // 1b. KR refresh time (set by 한국증시 최신화 / --kr-only)
    const elKrTime = document.getElementById('kr-updated-time');
    if (elKrTime) {
        elKrTime.textContent = dashboardData.kr_updated_at
            ? new Date(dashboardData.kr_updated_at).toLocaleString('ko-KR')
            : '-';
    }

    // 2. Universe Size
    elUniverseCount.textContent = dashboardData.universe_size || 0;

    // 3. Market Indicators
    renderIndicators();

    // 4. Options Flow
    renderOptionsFlow();

    // 5. Market Map Heatmap
    renderMarketMap();

    // 6. ETF Flows
    renderEtfFlows();

    // 7. AI Macro Analysis
    renderMacroAnalysis();

    // 8. Economic Calendar
    renderCalendar();

    // 9. Top Picks (Sidebar Table)
    renderTopPicks(isManual);
}

// Check if ticker is a Korean stock
function isKoreanStock(ticker) {
    return ticker.endsWith('.KS') || ticker.endsWith('.KQ') || /^\d{6}$/.test(ticker);
}

// Formatter helper for price, change, trading value, market cap
function formatValue(ticker, val, type) {
    if (val === null || val === undefined || isNaN(val)) return '-';
    const num = Number(val);
    const isKr = isKoreanStock(ticker);
    
    if (type === 'price') {
        if (ticker === '^TNX') return `${num.toFixed(2)}%`;
        if (isKr) return `₩${num.toLocaleString('ko-KR')}`;
        return `$${num.toFixed(2)}`;
    }
    
    if (type === 'change') {
        const sign = num >= 0 ? '+' : '';
        return `${sign}${num.toFixed(2)}%`;
    }
    
    if (type === 'trading_value') {
        if (isKr) {
            const valInEok = num / 100000000;
            return `${valInEok.toLocaleString('ko-KR', { maximumFractionDigits: 1 })}억`;
        } else {
            const valInM = num / 1000000;
            return `$${valInM.toLocaleString('en-US', { maximumFractionDigits: 1 })}M`;
        }
    }
    
    if (type === 'market_cap') {
        if (isKr) {
            if (num >= 1000000000000) {
                const valInJo = num / 1000000000000;
                return `${valInJo.toLocaleString('ko-KR', { maximumFractionDigits: 1 })}조`;
            } else {
                const valInEok = num / 100000000;
                return `${valInEok.toLocaleString('ko-KR', { maximumFractionDigits: 1 })}억`;
            }
        } else {
            if (num >= 1000000000) {
                const valInB = num / 1000000000;
                return `$${valInB.toLocaleString('en-US', { maximumFractionDigits: 1 })}B`;
            } else {
                const valInM = num / 1000000;
                return `$${valInM.toLocaleString('en-US', { maximumFractionDigits: 1 })}M`;
            }
        }
    }
    return val.toString();
}

// Render Market Indicators with Sparklines
function renderIndicators() {
    // Destroy previous sparkline charts to free memory
    sparklineCharts.forEach(c => c.destroy());
    sparklineCharts = [];

    elMarketIndicators.innerHTML = '';
    const indicators = dashboardData.market_indicators || {};
    const history = dashboardData.market_indicators_history || {};
    
    const indKeys = [
        { key: 'sp500', name: 'S&P 500' },
        { key: 'nasdaq', name: '나스닥 지수' },
        { key: 'dow_jones', name: '다우존스 지수' },
        { key: 'russell2000', name: '러셀 2000' },
        { key: 'kospi', name: '코스피 지수' },
        { key: 'kosdaq', name: '코스닥 지수' },
        { key: 'ust_10y', name: '미국 10년물 국채' },
        { key: 'vix', name: 'VIX 지수' },
        { key: 'skew', name: 'SKEW 지수' },
        { key: 'gold', name: '금 선물' },
        { key: 'wti_oil', name: 'WTI 원유' },
        { key: 'bitcoin', name: '비트코인' },
        { key: 'dxy', name: '달러 인덱스' },
        { key: 'usdkrw', name: '원/달러 환율' }
    ];

    const tickerMap = {
        'sp500': '^GSPC',
        'nasdaq': '^IXIC',
        'dow_jones': '^DJI',
        'russell2000': '^RUT',
        'kospi': '^KS11',
        'kosdaq': '^KQ11',
        'ust_10y': '^TNX',
        'vix': '^VIX',
        'skew': '^SKEW',
        'gold': 'GC=F',
        'wti_oil': 'CL=F',
        'bitcoin': 'BTC-USD',
        'dxy': 'DX-Y.NYB',
        'usdkrw': 'KRW=X'
    };

    indKeys.forEach(item => {
        const data = indicators[item.key];
        const card = document.createElement('div');
        card.className = 'indicator-card';
        card.style.cursor = 'pointer';
        
        card.addEventListener('click', () => {
            const sym = tickerMap[item.key];
            if (sym) selectStock(sym);
        });
        
        if (data) {
            const isUp = data.change_pct >= 0;
            const changeClass = isUp ? 'up' : 'down';
            const changeSign = isUp ? '+' : '';
            let valFormatted = formatValue(tickerMap[item.key], data.value, 'price');
            const changeFormatted = Number(data.change_pct).toFixed(2);

            card.innerHTML = `
                <span class="ind-name">${item.name}</span>
                <span class="ind-val">${valFormatted}</span>
                <span class="ind-change ${changeClass}">
                    ${isUp ? '▲' : '▼'} ${changeSign}${changeFormatted}%
                </span>
                <div class="sparkline-container">
                    <canvas class="sparkline-canvas" id="spark-${item.key}"></canvas>
                </div>
            `;
        } else {
            card.innerHTML = `
                <span class="ind-name">${item.name}</span>
                <span class="ind-val">-</span>
                <span class="ind-change text-muted">N/A</span>
            `;
        }
        elMarketIndicators.appendChild(card);

        // Render sparkline if history is available
        const histData = history[item.key];
        if (histData && data) {
            setTimeout(() => {
                drawSparkline(item.key, histData, data.change_pct >= 0);
            }, 50);
        }
    });
}

// Draw tiny sparkline line chart inside indicator card
function drawSparkline(key, histData, isUp) {
    const canvas = document.getElementById(`spark-${key}`);
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    
    // Sort dates
    const sortedDates = Object.keys(histData).sort();
    // Keep last 30 points to make it look clean
    const points = sortedDates.slice(-30).map(d => histData[d]);

    if (points.length === 0) return;

    const lineColor = isUp ? '#10b981' : '#ef4444';
    const gradient = ctx.createLinearGradient(0, 0, 0, 30);
    if (isUp) {
        gradient.addColorStop(0, 'rgba(16, 185, 129, 0.2)');
        gradient.addColorStop(1, 'rgba(16, 185, 129, 0)');
    } else {
        gradient.addColorStop(0, 'rgba(239, 68, 68, 0.2)');
        gradient.addColorStop(1, 'rgba(239, 68, 68, 0)');
    }

    const labels = points.map((_, i) => i);

    const chart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                data: points,
                borderColor: lineColor,
                borderWidth: 1.2,
                fill: true,
                backgroundColor: gradient,
                pointRadius: 0,
                tension: 0.2
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: { enabled: false }
            },
            scales: {
                x: { display: false },
                y: { display: false }
            }
        }
    });
    sparklineCharts.push(chart);
}

// Best display name for a pick: curated Korean map first, then the backend
// name (KR Korean names / US yfinance shortName), then the raw ticker.
function getStockName(pick) {
    const tk = (pick && pick.ticker) || '';
    return STOCK_NAMES[tk] || (pick && pick.name) || tk;
}

// Fill the chart-header title/subtitle, honoring the ticker<->name swap toggle.
// Remembers the last values so the toggle can re-apply without re-selecting.
function setDetailHeader(ticker, name) {
    _detailTicker = ticker;
    _detailName = name;
    if (headerSwapped) {
        elDetailTicker.textContent = name;    // big line shows the name
        elDetailName.textContent = ticker;    // subtitle shows the ticker
    } else {
        elDetailTicker.textContent = ticker;  // default: big line is the ticker
        elDetailName.textContent = name;
    }
}

// Numeric value of a pick for the active sort key (null = missing -> sorted last).
function pickSortValue(p, key) {
    switch (key) {
        case 'change': return p.daily_change_pct;
        case 'trading_value': return (p.current_price && p.volume) ? p.current_price * p.volume : null;
        case 'market_cap': return p.market_cap;
        case 'score': return p.composite_score;
        case 'price':
        default: return p.current_price;
    }
}

// Return a copy of picks sorted by the active key/direction (missing values last).
function sortPicks(picks) {
    return [...picks].sort((a, b) => {
        const av = pickSortValue(a, picksSortKey);
        const bv = pickSortValue(b, picksSortKey);
        if (av == null && bv == null) return 0;
        if (av == null) return 1;   // missing always last
        if (bv == null) return -1;
        return picksSortDir === 'desc' ? (bv - av) : (av - bv);
    });
}

// Render Top Picks in Sidebar Table (up to 20 items)
function renderTopPicks(isManual) {
    elPicksContainer.innerHTML = '';
    // KR picks during the day (08–20), US picks otherwise — follows the active market.
    const picks = (currentMarketView === 'kr'
        ? (dashboardData.kr_picks || [])
        : (dashboardData.top_picks || []));

    if (picks.length === 0) {
        elPicksContainer.innerHTML = `<tr><td colspan="6" style="text-align: center; color: var(--text-muted);">데이터가 없습니다.</td></tr>`;
        return;
    }

    // Display order follows the active sort button; rank column keeps the composite rank.
    sortPicks(picks).forEach((pick) => {
        const tr = document.createElement('tr');
        tr.className = 'pick-row-item';
        tr.setAttribute('data-ticker', pick.ticker);
        if (selectedTicker === pick.ticker) {
            tr.classList.add('active');
        }
        
        const changeVal = pick.daily_change_pct || 0;
        const changeClass = changeVal >= 0 ? 'up' : 'down';
        const priceFormatted = pick.current_price ? formatValue(pick.ticker, pick.current_price, 'price') : 'N/A';
        const changeFormatted = formatValue(pick.ticker, changeVal, 'change');
        
        // Trading Value = close * volume
        const tradingVal = (pick.current_price && pick.volume) ? (pick.current_price * pick.volume) : null;
        const tradingValFormatted = tradingVal ? formatValue(pick.ticker, tradingVal, 'trading_value') : '-';
        const mcapFormatted = pick.market_cap ? formatValue(pick.ticker, pick.market_cap, 'market_cap') : '-';

        tr.innerHTML = `
            <td style="text-align: center; font-weight: bold; color: var(--text-muted);">${pick.rank}</td>
            <td class="ticker-cell">
                <span class="pick-name">${getStockName(pick)}</span>
                <span class="pick-ticker">${pick.ticker}</span>
            </td>
            <td class="price-cell">${priceFormatted}</td>
            <td class="change-cell ${changeClass}">${changeFormatted}</td>
            <td class="val-cell">${tradingValFormatted}</td>
            <td class="val-cell">${mcapFormatted}</td>
        `;

        tr.addEventListener('click', () => selectStock(pick.ticker));
        elPicksContainer.appendChild(tr);
    });

    // Auto-select first stock on load or default based on active market
    if (picks.length > 0) {
        const defaultTicker = currentMarketView === 'kr' ? '005930.KS' : 'AAPL';
        const targetTicker = (isManual && selectedTicker) ? selectedTicker : (selectedTicker || defaultTicker);
        selectStock(targetTicker);
    }
}

// Initialize TradingView Lightweight Chart
function initCandleChart() {
    const container = document.getElementById('priceCandleChartContainer');
    if (!container) return;
    
    // Clear any previous chart
    container.innerHTML = '';
    
    try {
        priceChartInstance = LightweightCharts.createChart(container, {
            width: container.clientWidth,
            height: container.clientHeight || 230,
            layout: {
                background: { type: 'solid', color: '#161c2d' },
                textColor: '#94a3b8',
                fontFamily: 'Inter, sans-serif',
            },
            grid: {
                vertLines: { color: 'rgba(255, 255, 255, 0.04)' },
                horzLines: { color: 'rgba(255, 255, 255, 0.04)' },
            },
            rightPriceScale: {
                borderColor: 'rgba(255, 255, 255, 0.08)',
            },
            timeScale: {
                borderColor: 'rgba(255, 255, 255, 0.08)',
                timeVisible: true,
            },
            crosshair: {
                mode: LightweightCharts.CrosshairMode.Normal,
            },
        });

        candleSeries = priceChartInstance.addSeries(LightweightCharts.CandlestickSeries, {
            upColor: '#10b981',
            downColor: '#ef4444',
            borderDownColor: '#ef4444',
            borderUpColor: '#10b981',
            wickDownColor: '#ef4444',
            wickUpColor: '#10b981',
        });

        volumeSeries = priceChartInstance.addSeries(LightweightCharts.HistogramSeries, {
            color: 'rgba(59, 130, 246, 0.25)',
            priceFormat: {
                type: 'volume',
            },
            priceScaleId: '', // overlay
        });
        
        volumeSeries.priceScale().applyOptions({
            scaleMargins: {
                top: 0.8, // volume occupies bottom 20%
                bottom: 0,
            },
        });

        // Handle container resize dynamically
        new ResizeObserver(entries => {
            if (entries.length === 0 || !priceChartInstance) return;
            const { width, height } = entries[0].contentRect;
            priceChartInstance.resize(width, height || 230);
        }).observe(container);

    } catch (e) {
        console.error("Failed to initialize TradingView Lightweight Charts:", e);
        container.innerHTML = `<div class="flow-placeholder text-danger">차트 라이브러리 초기화 실패: ${e.message}</div>`;
    }
}

// Select a stock and update details + charts
async function selectStock(ticker) {
    selectedTicker = ticker;
    
    // Highlight in sidebar table
    document.querySelectorAll('.pick-row-item').forEach(tr => {
        if (tr.getAttribute('data-ticker') === ticker) {
            tr.classList.add('active');
        } else {
            tr.classList.remove('active');
        }
    });

    const picks = (dashboardData && dashboardData.top_picks) ? (dashboardData.top_picks || []) : [];
    let pick = picks.find(p => p.ticker === ticker);
    let isTopPick = true;

    if (!pick) {
        isTopPick = false;
        pick = {
            rank: '-',
            ticker: ticker,
            current_price: null,
            target_mean: null,
            upside_pct: null,
            ai_brief: null,
            factors: {
                momentum: 50, trend: 50, volume_surge: 50, rel_strength: 50, low_vol: 50, analyst_upside: 50
            }
        };
    }

    const isMacroIndicator = ticker.startsWith('^') || ticker.includes('=') || ticker === 'BTC-USD' || ticker === 'DX-Y.NYB';

    // Set header details
    if (isMacroIndicator) {
        elDetailRank.textContent = '지표';
    } else {
        elDetailRank.textContent = isTopPick ? `#${pick.rank}` : '일반';
    }

    // Custom stock names mapper including Heatmap ones
    const names = {
        'AAPL': 'Apple Inc.', 'MSFT': 'Microsoft Corporation', 'NVDA': 'NVIDIA Corporation',
        'AMZN': 'Amazon.com Inc.', 'GOOGL': 'Alphabet Inc. Class A', 'SPY': 'SPDR S&P 500 ETF Trust',
        'TSLA': 'Tesla, Inc.', 'META': 'Meta Platforms, Inc.', 'NFLX': 'Netflix, Inc.',
        'JPM': 'JPMorgan Chase & Co.', 'BAC': 'Bank of America Corporation', 'LLY': 'Eli Lilly and Company',
        'UNH': 'UnitedHealth Group Inc.', 'JNJ': 'Johnson & Johnson', 'AVGO': 'Broadcom Inc.',
        'CSCO': 'Cisco Systems, Inc.', 'ADBE': 'Adobe Inc.', 'CRM': 'Salesforce, Inc.',
        'WMT': 'Walmart Inc.', 'KO': 'The Coca-Cola Company', 'WFC': 'Wells Fargo & Company',
        'MS': 'Morgan Stanley', 'GS': 'The Goldman Sachs Group, Inc.', 'AXP': 'American Express Company',
        'ABBV': 'AbbVie Inc.', 'PFE': 'Pfizer Inc.', 'MRK': 'Merck & Co., Inc.',
        // Macro indicators
        '^GSPC': 'S&P 500 Index',
        '^IXIC': 'Nasdaq Composite Index',
        '^DJI': 'Dow Jones Industrial Average',
        '^RUT': 'Russell 2000 Index',
        '^KS11': 'KOSPI Composite Index',
        '^KQ11': 'KOSDAQ Composite Index',
        '^TNX': 'US 10-Year Treasury Yield',
        '^VIX': 'CBOE Volatility Index',
        '^SKEW': 'CBOE SKEW Index',
        'GC=F': 'Gold Futures',
        'CL=F': 'Crude Oil WTI Futures',
        'BTC-USD': 'Bitcoin USD',
        'DX-Y.NYB': 'US Dollar Index',
        'KRW=X': 'USD/KRW Exchange Rate'
    };
    const detailName = STOCK_NAMES[pick.ticker] || names[pick.ticker] || pick.name || 'Equities stock';
    setDetailHeader(pick.ticker, detailName);

    // Populate static data first
    const priceFormatted = pick.current_price ? formatValue(ticker, pick.current_price, 'price') : 'Loading...';
    const upsideFormatted = (isTopPick && pick.upside_pct) ? `${Number(pick.upside_pct).toFixed(2)}%` : '0.00%';
    const targetFormatted = (isTopPick && pick.target_mean) ? formatValue(ticker, pick.target_mean, 'price') : 'N/A';

    elDetailPrice.textContent = priceFormatted;
    elDetailChange.textContent = isTopPick ? upsideFormatted : '0.00%';
    elDetailChange.className = 'price-change-badge ' + ((isTopPick && parseFloat(upsideFormatted) >= 0) ? 'up' : 'down');
    elDetailTarget.textContent = targetFormatted;
    elDetailUpside.textContent = isTopPick ? upsideFormatted : '0.00%';

    // AI Brief
    if (isMacroIndicator) {
        elDetailAiBrief.innerHTML = `<p class="placeholder-text">선택하신 항목은 <strong>거시 경제 지표</strong>입니다. 거시 경제 상황에 대한 종합적인 분석은 하단의 'AI Macro Analysis (거시 경제 요약)'을 참고해 주세요.</p>`;
    } else if (isTopPick) {
        if (pick.ai_brief) {
            elDetailAiBrief.innerHTML = `<p>${pick.ai_brief}</p>`;
        } else {
            elDetailAiBrief.innerHTML = `<p class="placeholder-text">AI 분석 리포트가 생성되지 않았습니다. 백엔드를 AI 옵션(--skip-ai 없이)으로 실행해 주세요.</p>`;
        }
    } else {
        elDetailAiBrief.innerHTML = `<p class="placeholder-text">선택하신 종목은 <strong>일반 조회 종목</strong>입니다. AI 종목 브리프와 6대 팩터 분석은 'Top 스마트 머니 Pick'에 선정된 종목에 대해서만 제공됩니다.</p>`;
    }

    // Render Candlestick Chart
    await renderTrendChart(pick.ticker, pick.current_price);

    // Setup periodic polling for dynamic price updates
    startPriceUpdates(pick.ticker);
}

// Start price updates
function startPriceUpdates(ticker) {
    if (priceUpdateInterval) clearInterval(priceUpdateInterval);
    
    // Update every 15 seconds
    priceUpdateInterval = setInterval(async () => {
        try {
            const res = await fetch(`/api/stock/${ticker}?period=${selectedPeriod}`);
            if (!res.ok) return;
            const data = await res.json();
            
            // Only update UI if we are still looking at the same ticker
            if (selectedTicker === ticker) {
                elDetailPrice.textContent = formatValue(ticker, data.price, 'price');
                const isUp = data.change_pct >= 0;
                elDetailChange.textContent = `${isUp ? '+' : ''}${Number(data.change_pct).toFixed(2)}%`;
                elDetailChange.className = 'price-change-badge ' + (isUp ? 'up' : 'down');
            }
        } catch (e) {
            console.warn('Live price update failed:', e);
        }
    }, 15000);
}

// Render Factor Radar Chart using Chart.js
// NOTE: the 6-Factor panel was removed from the UI. This is kept as a no-op-safe
// helper so any stray call won't throw; it returns early when the canvas is absent.
function renderRadarChart(factors, isTopPick = true) {
    const canvas = document.getElementById('factorRadarChart');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');

    if (factorChartInstance) {
        factorChartInstance.destroy();
    }

    const labels = ['Momentum', 'Trend', 'Volume Surge', 'Rel. Strength', 'Low Volatility', 'Analyst Upside'];
    const dataValues = [
        factors.momentum || 0,
        factors.trend || 0,
        factors.volume_surge || 0,
        factors.rel_strength || 0,
        factors.low_vol || 0,
        factors.analyst_upside || 0
    ];

    const labelText = isTopPick ? 'Factor Score (0-100)' : '팩터 분석 미제공 (일반 종목)';
    const colorBorder = isTopPick ? '#3b82f6' : '#64748b';
    const colorBg = isTopPick ? 'rgba(59, 130, 246, 0.25)' : 'rgba(100, 116, 139, 0.15)';

    factorChartInstance = new Chart(ctx, {
        type: 'radar',
        data: {
            labels: labels,
            datasets: [{
                label: labelText,
                data: dataValues,
                backgroundColor: colorBg,
                borderColor: colorBorder,
                pointBackgroundColor: isTopPick ? '#00f0ff' : '#64748b',
                pointBorderColor: '#fff',
                pointHoverBackgroundColor: '#fff',
                pointHoverBorderColor: colorBorder,
                borderWidth: 2
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false }
            },
            scales: {
                r: {
                    grid: { color: 'rgba(255, 255, 255, 0.08)' },
                    angleLines: { color: 'rgba(255, 255, 255, 0.08)' },
                    pointLabels: { color: '#94a3b8', font: { size: 10, family: 'Inter' } },
                    ticks: { display: false },
                    suggestedMin: 0,
                    suggestedMax: 100
                }
            }
        }
    });
}

// Render Candlestick Chart by querying Flask backend
async function renderTrendChart(ticker, fallbackPrice) {
    if (!priceChartInstance || !candleSeries || !volumeSeries) return;

    let candleData = [];
    let volumeData = [];
    let isUp = true;

    try {
        const response = await fetch(`/api/stock/${ticker}?period=${selectedPeriod}`);
        if (!response.ok) throw new Error("API call failed");
        const data = await response.json();
        
        const chart = data.chart;
        for (let i = 0; i < chart.dates.length; i++) {
            const timeVal = chart.dates[i];
            
            candleData.push({
                time: timeVal,
                open: chart.opens[i],
                high: chart.highs[i],
                low: chart.lows[i],
                close: chart.closes[i]
            });
            
            const isBarUp = chart.closes[i] >= chart.opens[i];
            let colorVal = 'rgba(59, 130, 246, 0.3)'; // fallback
            if (mapColorMode === 'us') {
                colorVal = isBarUp ? 'rgba(16, 185, 129, 0.3)' : 'rgba(239, 68, 68, 0.3)';
            } else {
                colorVal = isBarUp ? 'rgba(239, 68, 68, 0.3)' : 'rgba(37, 99, 235, 0.3)';
            }
            volumeData.push({
                time: timeVal,
                value: chart.volumes[i],
                color: colorVal
            });
        }
        
        isUp = data.change_pct >= 0;

        // Sync header details
        elDetailPrice.textContent = formatValue(ticker, data.price, 'price');
        elDetailChange.textContent = formatValue(ticker, data.change_pct, 'change');
        elDetailChange.className = 'price-change-badge ' + (isUp ? 'up' : 'down');
        
        // Sync candlestick colors with active color scheme preference
        if (mapColorMode === 'us') {
            candleSeries.applyOptions({
                upColor: '#10b981',
                downColor: '#ef4444',
                borderDownColor: '#ef4444',
                borderUpColor: '#10b981',
                wickDownColor: '#ef4444',
                wickUpColor: '#10b981',
            });
        } else {
            candleSeries.applyOptions({
                upColor: '#ef4444',
                downColor: '#2563eb',
                borderDownColor: '#2563eb',
                borderUpColor: '#ef4444',
                wickDownColor: '#2563eb',
                wickUpColor: '#ef4444',
            });
        }

        // Apply data
        candleSeries.setData(candleData);
        volumeSeries.setData(volumeData);

        // Fit content
        priceChartInstance.timeScale().fitContent();

    } catch (e) {
        console.warn('Failed to render trend chart for', ticker, e);
        // Clear chart data on failure
        candleSeries.setData([]);
        volumeSeries.setData([]);
    }
}

// Render Options Flow List
function renderOptionsFlow() {
    elOptionsFlowContent.innerHTML = '';
    const flows = dashboardData.options_flow || [];

    if (flows.length === 0) {
        // Fallback demo data to make it look premium
        const mockFlows = [
            { ticker: 'AAPL', call_put_ratio: 1.8, posture: 'bullish' },
            { ticker: 'NVDA', call_put_ratio: 2.4, posture: 'bullish' },
            { ticker: 'MSFT', call_put_ratio: 1.1, posture: 'neutral' },
            { ticker: 'AMZN', call_put_ratio: 0.7, posture: 'bearish' }
        ];
        mockFlows.forEach(flow => {
            elOptionsFlowContent.appendChild(createOptionRow(flow));
        });
        return;
    }

    flows.forEach(flow => {
        elOptionsFlowContent.appendChild(createOptionRow(flow));
    });
}

function createOptionRow(flow) {
    const row = document.createElement('div');
    row.className = 'options-row-item';
    
    let postureText = 'Neutral';
    let badgeClass = 'orange';
    if (flow.posture === 'bullish') {
        postureText = 'Long';
        badgeClass = 'green';
    } else if (flow.posture === 'bearish') {
        postureText = 'Short';
        badgeClass = 'red';
    }

    row.innerHTML = `
        <span class="opt-ticker">${flow.ticker}</span>
        <span class="text-secondary font-mono text-sm">C/P: ${(flow.call_put_ratio || 1.0).toFixed(1)}</span>
        <span class="opt-badge ${badgeClass}">${postureText}</span>
    `;
    return row;
}

// Render ETF Flows List based on current active tab
function renderEtfFlows() {
    elEtfFlowsContainer.innerHTML = '';
    const etfData = dashboardData.etf_flows || {};
    
    let list = [];
    if (currentEtfTab === 'inflow') {
        list = etfData.top_inflow || [];
    } else {
        list = etfData.top_outflow || [];
    }

    if (list.length === 0) {
        // Fallback premium mock data
        const mockInflows = [
            { ticker: 'SPY', flow_million: 1450.4 },
            { ticker: 'QQQ', flow_million: 980.2 },
            { ticker: 'IWM', flow_million: 430.7 },
            { ticker: 'XLF', flow_million: 310.1 }
        ];
        const mockOutflows = [
            { ticker: 'HYG', flow_million: -540.2 },
            { ticker: 'EEM', flow_million: -310.5 },
            { ticker: 'TLT', flow_million: -220.8 },
            { ticker: 'GLD', flow_million: -140.3 }
        ];
        
        list = currentEtfTab === 'inflow' ? mockInflows : mockOutflows;
    }

    list.forEach(item => {
        const el = document.createElement('div');
        el.className = 'etf-item';
        const val = Number(item.flow_million);
        const valClass = val >= 0 ? 'up' : 'down';
        const sign = val >= 0 ? '+' : '';

        el.innerHTML = `
            <span class="etf-ticker">${item.ticker}</span>
            <span class="etf-flow-val ${valClass}">${sign}${val.toLocaleString('ko-KR')}M</span>
        `;
        elEtfFlowsContainer.appendChild(el);
    });
}

// Render AI Macro Analysis summaries
function renderMacroAnalysis() {
    const macro = dashboardData.macro_analysis || {};
    
    if (macro.claude) {
        elMacroClaudeContent.innerHTML = `<p>${macro.claude}</p>`;
    } else {
        elMacroClaudeContent.innerHTML = `
            <p class="placeholder-text">
                Claude 분석 결과가 없습니다.<br>
                <code>.env</code> 파일에 <code>ANTHROPIC_API_KEY</code>를 등록하고 백엔드를 실행하세요.
            </p>`;
    }

    if (macro.gemini) {
        elMacroGeminiContent.innerHTML = `<p>${macro.gemini}</p>`;
    } else {
        elMacroGeminiContent.innerHTML = `
            <p class="placeholder-text">
                Gemini 분석 결과가 없습니다.<br>
                <code>.env</code> 파일에 <code>GEMINI_API_KEY</code>를 등록하고 백엔드를 실행하세요.
            </p>`;
    }
}

// Render Economic Calendar List
function renderCalendar() {
    elCalendarContainer.innerHTML = '';
    const calendar = dashboardData.economic_calendar || [];

    if (calendar.length === 0) {
        // Fallback mock dates
        const mockCalendar = [
            { date: '2026-06-23', event: '신규 주택판매건수 발표', release_time: '10:00 AM EST' },
            { date: '2026-06-25', event: '미국 1분기 GDP (최종치)', release_time: '08:30 AM EST' },
            { date: '2026-06-26', event: '근원 개인소비지출(PCE) 물가지수', release_time: '08:30 AM EST' }
        ];
        mockCalendar.forEach(item => {
            elCalendarContainer.appendChild(createCalItem(item));
        });
        return;
    }

    calendar.slice(0, 5).forEach(item => {
        elCalendarContainer.appendChild(createCalItem(item));
    });
}

function createCalItem(item) {
    const el = document.createElement('div');
    el.className = 'cal-item';
    
    const d = new Date(item.date);
    const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    const monthStr = months[d.getMonth()] || 'N/A';
    const dayStr = d.getDate() || '--';

    el.innerHTML = `
        <div class="cal-date-box">
            <span class="cal-month">${monthStr}</span>
            <span class="cal-day">${dayStr}</span>
        </div>
        <div class="cal-details">
            <span class="cal-event">${item.event}</span>
            <span class="cal-release">${item.release_time || 'All Day'}</span>
        </div>
    `;
    return el;
}

// Utility rounding
function round(value, decimals) {
    return Number(Math.round(value + 'e' + decimals) + 'e-' + decimals);
}

// --- Modal management ---
function openModal(id) {
    document.getElementById(id).classList.add('open');
}

function closeModal(id) {
    document.getElementById(id).classList.remove('open');
}

// Global modal close handlers
window.closeModal = closeModal;

// Keys Configuration lists
const SECRET_KEYS = ["FRED_API_KEY", "DART_API_KEY", "KIS_APP_KEY", "KIS_APP_SECRET", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "OPTIONS_FLOW_API_KEY", "ETF_FLOW_API_KEY"];
const PLAIN_KEYS  = ["OPTIONS_FLOW_PROVIDER", "ETF_FLOW_PROVIDER", "CLAUDE_MODEL", "GEMINI_MODEL"];
const KEY_LABELS = {
    FRED_API_KEY: "FRED API Key (무료 지표 수집용)",
    DART_API_KEY: "DART API Key (한국 전자공시 수집용, opendart.fss.or.kr)",
    KIS_APP_KEY: "한국투자증권 KIS App Key (한국증시 최신화용)",
    KIS_APP_SECRET: "한국투자증권 KIS App Secret",
    ANTHROPIC_API_KEY: "Anthropic (Claude) API Key (종목 분석용)",
    GEMINI_API_KEY: "Google AI Studio (Gemini) API Key (매크로 분석용)",
    OPTIONS_FLOW_API_KEY: "옵션 플로우 API Key (유료, 선택사항)",
    ETF_FLOW_API_KEY: "ETF 자금 흐름 API Key (유료, 선택사항)",
    OPTIONS_FLOW_PROVIDER: "옵션 플로우 데이터 제공사",
    ETF_FLOW_PROVIDER: "ETF 자금 흐름 데이터 제공사",
    CLAUDE_MODEL: "Claude AI 모델명 (기본: claude-opus-4-8)",
    GEMINI_MODEL: "Gemini AI 모델명 (기본: gemini-2.5-pro)"
};

// Load saved key configurations and build settings form
async function loadKeysForm() {
    try {
        const res = await fetch("/api/keys");
        if (!res.ok) throw new Error();
        const keyStatus = await res.json();
        
        const form = document.getElementById("keys-form");
        form.innerHTML = "";

        // Secrets
        SECRET_KEYS.forEach(f => {
            const s = keyStatus[f] || {};
            const html = `
                <div>
                    <label>${KEY_LABELS[f]}</label>
                    <div class="field-row">
                        <span class="dot ${s.set ? 'set' : ''}"></span>
                        <input type="password" data-key="${f}" placeholder="${s.set ? '저장됨 — 변경 시에만 입력하세요' : '미설정'}">
                    </div>
                    <div class="hint">${s.set ? '현재 마스킹된 힌트: ' + (s.hint || '••••') : ''}</div>
                </div>
            `;
            form.insertAdjacentHTML("beforeend", html);
        });

        // Plain values
        PLAIN_KEYS.forEach(f => {
            const s = keyStatus[f] || {};
            const html = `
                <div>
                    <label>${KEY_LABELS[f]}</label>
                    <div class="field-row">
                        <span class="dot ${s.set ? 'set' : ''}"></span>
                        <input type="text" data-key="${f}" value="${s.value || ''}" placeholder="기본값 사용">
                    </div>
                    <div class="hint"></div>
                </div>
            `;
            form.insertAdjacentHTML("beforeend", html);
        });
    } catch (e) {
        console.error('Failed to load keys status:', e);
    }
}

// POST API Keys
async function saveKeys() {
    const payload = {};
    document.querySelectorAll("[data-key]").forEach(el => {
        const k = el.dataset.key;
        const v = el.value.trim();
        // Secrets: only send if user entered something new (blank = no change)
        if (SECRET_KEYS.includes(k)) {
            if (v) payload[k] = v;
        } else {
            payload[k] = v;
        }
    });

    const statusEl = document.getElementById("keys-save-status");
    statusEl.textContent = "저장 중...";
    statusEl.style.color = "var(--text-secondary)";

    try {
        const res = await fetch("/api/keys", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        
        if (data.ok) {
            statusEl.textContent = "✓ API 키가 성공적으로 저장되었습니다.";
            statusEl.style.color = "var(--color-up)";
            loadKeysForm();
        } else {
            throw new Error();
        }
    } catch (e) {
        statusEl.textContent = "오류: 저장에 실패했습니다.";
        statusEl.style.color = "var(--color-down)";
    }
    setTimeout(() => { statusEl.textContent = ""; }, 3000);
}

// Pipeline Execution variables
let pipelinePollInterval = null;

// Enable/disable both run buttons together while a run is in progress.
function setPipelineButtonsRunning(running) {
    const runBtn = document.getElementById("run-pipeline-start-btn");
    const krBtn = document.getElementById("run-kr-refresh-btn");
    if (runBtn) {
        runBtn.disabled = running;
        runBtn.textContent = running ? "실행 중..." : "파이프라인 실행";
    }
    if (krBtn) {
        krBtn.disabled = running;
        krBtn.textContent = running ? "실행 중..." : "🇰🇷 한국증시 최신화 (KIS)";
    }
}

// Trigger the pipeline execution. krOnly=true refreshes just the Korean market
// data (KIS API when keys are set) without touching the ~500-ticker US universe.
async function triggerPipeline(krOnly = false) {
    const skipAi = document.getElementById("pipeline-skip-ai-chk").checked;
    setPipelineButtonsRunning(true);

    try {
        const res = await fetch("/api/run", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ skip_ai: skipAi, kr_only: krOnly })
        });
        const data = await res.json();

        if (data.ok) {
            document.getElementById("pipeline-log-console").textContent = krOnly
                ? "한국증시 데이터 최신화를 시작했습니다 (KIS 키 설정 시 KIS API, 아니면 yfinance)...\n"
                : "파이프라인이 백그라운드에서 실행을 시작했습니다...\n";
            updatePipelineStatusBadge("running", "실행 중");
            startPipelinePolling();
        } else {
            alert("에러: " + (data.error || "실행에 실패했습니다."));
            setPipelineButtonsRunning(false);
        }
    } catch (e) {
        console.error('Failed to trigger pipeline:', e);
        setPipelineButtonsRunning(false);
    }
}

// Poll pipeline run status
function startPipelinePolling() {
    if (pipelinePollInterval) clearInterval(pipelinePollInterval);
    
    pipelinePollInterval = setInterval(async () => {
        try {
            const res = await fetch("/api/status");
            if (!res.ok) return;
            const data = await res.json();

            // Render log text
            const logEl = document.getElementById("pipeline-log-console");
            if (data.log) {
                logEl.textContent = data.log;
                // Auto scroll console to bottom
                logEl.scrollTop = logEl.scrollHeight;
            }

            if (!data.running) {
                clearInterval(pipelinePollInterval);
                setPipelineButtonsRunning(false);

                if (data.returncode === 0) {
                    updatePipelineStatusBadge("completed", "완료");
                    // Auto refresh dashboard data
                    fetchDashboardData();
                } else {
                    updatePipelineStatusBadge("failed", `실패 (code ${data.returncode})`);
                }
            } else {
                updatePipelineStatusBadge("running", "실행 중");
            }
        } catch (e) {
            console.warn('Polling status failed:', e);
        }
    }, 1500);
}

// Check pipeline status on console modal open
async function checkPipelineStatus() {
    try {
        const res = await fetch("/api/status");
        if (!res.ok) return;
        const data = await res.json();
        
        const logEl = document.getElementById("pipeline-log-console");
        if (data.log) {
            logEl.textContent = data.log;
            logEl.scrollTop = logEl.scrollHeight;
        }

        if (data.running) {
            setPipelineButtonsRunning(true);
            updatePipelineStatusBadge("running", "실행 중");
            startPipelinePolling();
        } else {
            setPipelineButtonsRunning(false);
            if (data.returncode === null) {
                updatePipelineStatusBadge("idle", "대기 중");
            } else if (data.returncode === 0) {
                updatePipelineStatusBadge("completed", "완료");
            } else {
                updatePipelineStatusBadge("failed", `실패 (code ${data.returncode})`);
            }
        }
    } catch (e) {
        console.warn('Failed to check pipeline status:', e);
    }
}

// Helper to update pipeline status badge CSS
function updatePipelineStatusBadge(statusClass, text) {
    const badge = document.getElementById("pipeline-status-badge");
    badge.className = `pipeline-status-badge ${statusClass}`;
    badge.textContent = text;
}

// US Heatmap Sector Stocks list
const US_SECTOR_STOCKS = {
    'Technology': ['AAPL', 'MSFT', 'NVDA', 'AVGO', 'ADBE', 'CRM'],
    'Consumer': ['AMZN', 'TSLA', 'META', 'NFLX', 'WMT', 'KO'],
    'Healthcare': ['LLY', 'UNH', 'JNJ', 'MRK', 'ABBV', 'PFE'],
    'Finance': ['JPM', 'BAC', 'WFC', 'MS', 'GS', 'AXP']
};

// KR Heatmap Sector Stocks list (KOSPI 200 representation)
const KR_SECTOR_STOCKS = {
    '반도체/IT': ['005930.KS', '000660.KS', '373220.KS', '006400.KS', '066570.KS', '009150.KS'],
    '자동차/제조': ['005380.KS', '000270.KS', '012330.KS', '010140.KS', '329180.KS', '042660.KS'],
    '바이오/헬스': ['207940.KS', '068270.KS', '000100.KS', '128940.KS', '326030.KS'],
    '철강/화학/소재': ['051910.KS', '005490.KS', '003670.KS', '096770.KS', '010130.KS', '010950.KS'],
    '서비스/플랫폼': ['035420.KS', '035720.KS', '259960.KS', '036570.KS'],
    '금융/지주': ['105560.KS', '055550.KS', '086790.KS', '138040.KS', '032830.KS', '316140.KS']
};

// Heatmap Stock relative weights (representing market cap sizes)
const US_STOCK_WEIGHTS = {
    'MSFT': 32, 'AAPL': 30, 'NVDA': 30, 'AVGO': 8, 'ADBE': 5, 'CRM': 5,
    'AMZN': 35, 'META': 30, 'TSLA': 20, 'NFLX': 8, 'WMT': 7, 'KO': 5,
    'LLY': 35, 'UNH': 25, 'JNJ': 18, 'MRK': 12, 'ABBV': 10, 'PFE': 6,
    'JPM': 40, 'BAC': 22, 'WFC': 16, 'GS': 10, 'MS': 10, 'AXP': 8
};

const KR_STOCK_WEIGHTS = {
    '005930.KS': 45, '000660.KS': 30, '373220.KS': 18, '006400.KS': 10, '066570.KS': 8, '009150.KS': 6,
    '005380.KS': 25, '000270.KS': 20, '012330.KS': 12, '010140.KS': 8, '329180.KS': 8, '042660.KS': 6,
    '207940.KS': 28, '068270.KS': 24, '000100.KS': 10, '128940.KS': 8, '326030.KS': 6,
    '051910.KS': 18, '005490.KS': 22, '003670.KS': 10, '096770.KS': 8, '010130.KS': 12, '010950.KS': 8,
    '035420.KS': 18, '035720.KS': 15, '259960.KS': 12, '036570.KS': 8,
    '105560.KS': 20, '055550.KS': 18, '086790.KS': 14, '138040.KS': 15, '032830.KS': 10, '316140.KS': 8
};

// Korean names mapping for US and KR stocks
const STOCK_NAMES = {
    // US Stocks
    'AAPL': '애플', 'MSFT': '마이크로소프트', 'NVDA': '엔비디아', 'AMZN': '아마존',
    'GOOGL': '구글', 'TSLA': '테슬라', 'META': '메타', 'NFLX': '넷플릭스',
    'AVGO': '브로드컴', 'ADBE': '어도비', 'CRM': '세일즈포스',
    'LLY': '일라이릴리', 'UNH': '유나이티드헬스', 'JNJ': '존슨앤존슨', 'MRK': '머크',
    'ABBV': '애브비', 'PFE': '화이자', 'WMT': '월마트', 'KO': '코카콜라',
    'JPM': 'JP모건', 'BAC': '뱅크오브아메리카', 'WFC': '웰스파고', 'GS': '골드만삭스',
    'MS': '모건스탠리', 'AXP': '아메리칸익스프레스',
    'V': '비자', 'MA': '마스터카드', 'HD': '홈디포', 'COST': '코스트코',
    'PG': 'P&G', 'XOM': '엑슨모빌', 'BRK-B': '버크셔해서웨이', 'SPY': 'S&P500 ETF',
    // KR Stocks
    '005930.KS': '삼성전자', '000660.KS': 'SK하이닉스', '373220.KS': 'LG에너지솔루션',
    '006400.KS': '삼성SDI', '066570.KS': 'LG전자', '009150.KS': '삼성전기',
    '005380.KS': '현대차', '000270.KS': '기아', '012330.KS': '현대모비스',
    '010140.KS': '삼성중공업', '329180.KS': 'HD현대중공업', '042660.KS': '한화오션',
    '207940.KS': '삼성바이오로직스', '068270.KS': '셀트리온', '000100.KS': '유한양행',
    '128940.KS': '한미약품', '326030.KS': 'SK바이오팜', '051910.KS': 'LG화학',
    '005490.KS': 'POSCO홀딩스', '003670.KS': '포스코퓨처엠', '096770.KS': 'SK이노베이션',
    '010130.KS': '고려아연', '010950.KS': 'S-Oil', '035420.KS': 'NAVER',
    '035720.KS': '카카오', '259960.KS': '크래프톤', '036570.KS': '엔씨소프트',
    '105560.KS': 'KB금융', '055550.KS': '신한지주', '086790.KS': '하나금융지주',
    '138040.KS': '메리츠금융', '032830.KS': '삼성생명', '316140.KS': '우리금융지주'
};

// Binary Split Treemap Layout Algorithm
function layoutTreemap(rect, items) {
    if (items.length === 0) return [];
    if (items.length === 1) {
        return [{ ...items[0], rect }];
    }
    
    let bestSplit = 0;
    let minDiff = Infinity;
    const totalWeight = items.reduce((sum, item) => sum + item.weight, 0);
    
    let leftWeight = 0;
    for (let i = 0; i < items.length - 1; i++) {
        leftWeight += items[i].weight;
        const rightWeight = totalWeight - leftWeight;
        const diff = Math.abs(leftWeight - rightWeight);
        if (diff < minDiff) {
            minDiff = diff;
            bestSplit = i;
        }
    }
    
    const leftItems = items.slice(0, bestSplit + 1);
    const rightItems = items.slice(bestSplit + 1);
    const leftTotal = leftItems.reduce((sum, item) => sum + item.weight, 0);
    
    const ratio = leftTotal / totalWeight;
    const splitVertical = rect.w > rect.h;
    
    let leftRect, rightRect;
    if (splitVertical) {
        leftRect = { x: rect.x, y: rect.y, w: rect.w * ratio, h: rect.h };
        rightRect = { x: rect.x + rect.w * ratio, y: rect.y, w: rect.w * (1 - ratio), h: rect.h };
    } else {
        leftRect = { x: rect.x, y: rect.y, w: rect.w, h: rect.h * ratio };
        rightRect = { x: rect.x, y: rect.y + rect.h * ratio, w: rect.w, h: rect.h * (1 - ratio) };
    }
    
    return [
        ...layoutTreemap(leftRect, leftItems),
        ...layoutTreemap(rightRect, rightItems)
    ];
}

// Get or create floating tooltip container dynamically
function getOrCreateTooltip() {
    if (!elMapTooltip) {
        elMapTooltip = document.getElementById('map-tooltip');
        if (!elMapTooltip) {
            elMapTooltip = document.createElement('div');
            elMapTooltip.id = 'map-tooltip';
            document.body.appendChild(elMapTooltip);
        }
    }
    return elMapTooltip;
}

// Show floating glassmorphic tooltip
function showTooltip(e, ticker) {
    const tooltip = getOrCreateTooltip();
    const displayName = STOCK_NAMES[ticker] || ticker;
    
    const data = marketMapDataCache[ticker];
    
    let priceText = 'Loading...';
    let changeText = 'Loading...';
    let changeClass = 'flat';
    let mcapText = 'Loading...';
    
    if (data) {
        priceText = formatValue(ticker, data.price, 'price');
        
        const isUp = data.change_pct >= 0;
        const sign = isUp ? '+' : '';
        changeText = `${sign}${data.change_pct.toFixed(2)}%`;
        
        if (mapColorMode === 'us') {
            changeClass = isUp ? 'up' : 'down';
        } else {
            changeClass = isUp ? 'kr-up' : 'kr-down';
        }
        
        mcapText = data.market_cap ? formatValue(ticker, data.market_cap, 'market_cap') : '-';
    }
    
    tooltip.innerHTML = `
        <div class="tooltip-header">
            <span class="tooltip-name">${displayName}</span>
            <span class="tooltip-ticker">${ticker}</span>
        </div>
        <div class="tooltip-row">
            <span class="tooltip-label">현재가</span>
            <span class="tooltip-value">${priceText}</span>
        </div>
        <div class="tooltip-row">
            <span class="tooltip-label">등락률</span>
            <span class="tooltip-value tooltip-change ${changeClass}">${changeText}</span>
        </div>
        <div class="tooltip-row">
            <span class="tooltip-label">시가총액</span>
            <span class="tooltip-value">${mcapText}</span>
        </div>
    `;
    
    tooltip.classList.add('visible');
    moveTooltip(e);
}

// Move floating tooltip to follow cursor
function moveTooltip(e) {
    const tooltip = getOrCreateTooltip();
    
    const tooltipWidth = tooltip.offsetWidth;
    const tooltipHeight = tooltip.offsetHeight;
    
    let x = e.clientX + 15;
    let y = e.clientY + 15;
    
    if (x + tooltipWidth > window.innerWidth) {
        x = e.clientX - tooltipWidth - 15;
    }
    if (y + tooltipHeight > window.innerHeight) {
        y = e.clientY - tooltipHeight - 15;
    }
    
    tooltip.style.left = `${x}px`;
    tooltip.style.top = `${y}px`;
}

// Hide tooltip
function hideTooltip() {
    const tooltip = getOrCreateTooltip();
    tooltip.classList.remove('visible');
}

// Render Market Map Sectors and initial mock tiles
function renderMarketMap() {
    const container = document.getElementById('market-map-content');
    if (!container) return;

    container.innerHTML = '';
    
    // Cached/mock starting changes to look premium instantly before background load completes
    const mockChanges = {
        'AAPL': 1.2, 'MSFT': -0.4, 'NVDA': 3.1, 'AVGO': 0.8, 'ADBE': -1.1, 'CRM': -0.2,
        'AMZN': 1.5, 'TSLA': -2.3, 'META': 0.5, 'NFLX': 2.1, 'WMT': 0.1, 'KO': -0.3,
        'LLY': 2.4, 'UNH': -0.7, 'JNJ': -0.1, 'MRK': 0.6, 'ABBV': 0.9, 'PFE': -1.8,
        'JPM': 0.4, 'BAC': -0.9, 'WFC': -0.5, 'MS': 0.2, 'GS': 0.7, 'AXP': 1.1,
        // KR
        '005930.KS': 1.5, '000660.KS': 2.8, '373220.KS': -1.1, '006400.KS': -0.5, '066570.KS': 0.8, '009150.KS': 0.3,
        '005380.KS': 2.1, '000270.KS': 1.4, '012330.KS': 0.5, '010140.KS': -2.0, '329180.KS': 1.1, '042660.KS': -1.5,
        '207940.KS': 0.9, '068270.KS': 1.7, '000100.KS': 4.2, '128940.KS': 0.8, '326030.KS': -0.4,
        '051910.KS': -2.2, '005490.KS': -1.4, '003670.KS': -3.1, '096770.KS': -0.8, '010130.KS': 12.5, '010950.KS': 0.2,
        '035420.KS': -0.9, '035720.KS': -1.1, '259960.KS': 2.3, '036570.KS': 0.4,
        '105560.KS': 3.5, '055550.KS': 2.4, '086790.KS': 1.8, '138040.KS': 4.1, '032830.KS': 0.7, '316140.KS': 1.2
    };

    const width = container.clientWidth || 280;
    const height = container.clientHeight || 520;
    const mainRect = { x: 0, y: 0, w: width, h: height };

    const activeSectors = currentMarketView === 'kr' ? KR_SECTOR_STOCKS : US_SECTOR_STOCKS;
    const activeWeights = currentMarketView === 'kr' ? KR_STOCK_WEIGHTS : US_STOCK_WEIGHTS;
    
    const sectorWeights = currentMarketView === 'kr' ? 
        { '반도체/IT': 32, '자동차/제조': 20, '바이오/헬스': 18, '철강/화학/소재': 15, '서비스/플랫폼': 12, '금융/지주': 10 } :
        { 'Technology': 35, 'Consumer': 25, 'Healthcare': 22, 'Finance': 18 };

    const sectors = Object.keys(activeSectors).map(name => ({
        name: name,
        weight: sectorWeights[name] || 10,
        tickers: activeSectors[name]
    }));

    sectors.sort((a, b) => b.weight - a.weight);

    const sectorLayouts = layoutTreemap(mainRect, sectors);

    sectorLayouts.forEach(secLayout => {
        const sectorRect = secLayout.rect;
        
        const sectorEl = document.createElement('div');
        sectorEl.className = 'market-sector';
        sectorEl.style.left = `${sectorRect.x}px`;
        sectorEl.style.top = `${sectorRect.y}px`;
        sectorEl.style.width = `${sectorRect.w}px`;
        sectorEl.style.height = `${sectorRect.h}px`;
        
        const nameEl = document.createElement('span');
        nameEl.className = 'sector-name';
        nameEl.textContent = secLayout.name;
        nameEl.style.position = 'absolute';
        nameEl.style.left = '6px';
        nameEl.style.top = '4px';
        nameEl.style.fontSize = '0.62rem';
        nameEl.style.height = '14px';
        sectorEl.appendChild(nameEl);

        const innerRect = { 
            x: 2, 
            y: 18, 
            w: Math.max(sectorRect.w - 4, 1), 
            h: Math.max(sectorRect.h - 20, 1) 
        };

        const stockItems = secLayout.tickers.map(ticker => ({
            ticker: ticker,
            weight: activeWeights[ticker] || 10
        }));
        
        stockItems.sort((a, b) => b.weight - a.weight);

        const stockLayouts = layoutTreemap(innerRect, stockItems);

        stockLayouts.forEach(stock => {
            const ticker = stock.ticker;
            const initialChange = mockChanges[ticker] || 0;
            const sign = initialChange >= 0 ? '+' : '';
            
            const tile = document.createElement('div');
            tile.className = `map-tile ${getChangeClass(initialChange)}`;
            tile.setAttribute('data-ticker', ticker);
            tile.style.left = `${stock.rect.x}px`;
            tile.style.top = `${stock.rect.y}px`;
            tile.style.width = `${Math.max(stock.rect.w - 1.5, 1)}px`;
            tile.style.height = `${Math.max(stock.rect.h - 1.5, 1)}px`;

            const showChange = stock.rect.w > 45 && stock.rect.h > 35;
            const showTicker = stock.rect.w > 26 && stock.rect.h > 18;
            const fontSize = getFontSize(stock.rect.w);

            const displayName = STOCK_NAMES[ticker] || ticker;

            tile.innerHTML = `
                ${showTicker ? `<span class="tile-ticker" style="font-size: ${fontSize}rem;">${displayName}</span>` : ''}
                ${showChange ? `<span class="tile-change">${sign}${initialChange.toFixed(1)}%</span>` : ''}
            `;
            
            tile.addEventListener('click', () => selectStock(ticker));
            
            tile.addEventListener('mouseenter', (e) => showTooltip(e, ticker));
            tile.addEventListener('mousemove', (e) => moveTooltip(e));
            tile.addEventListener('mouseleave', () => hideTooltip());

            sectorEl.appendChild(tile);
        });

        container.appendChild(sectorEl);
    });

    fetchMarketMapData();
}

// Fetch real-time stock changes from the local Flask proxy sequentially
async function fetchMarketMapData() {
    mapFetchSessionId++;
    const currentSession = mapFetchSessionId;
    
    const activeSectors = currentMarketView === 'kr' ? KR_SECTOR_STOCKS : US_SECTOR_STOCKS;
    const allTickers = Object.values(activeSectors).flat();
    
    for (const ticker of allTickers) {
        if (currentSession !== mapFetchSessionId) {
            console.log('Market map fetch session cancelled.');
            return;
        }
        try {
            const res = await fetch(`/api/stock/${ticker}`);
            if (res.ok) {
                const data = await res.json();
                if (currentSession !== mapFetchSessionId) return;
                
                marketMapDataCache[ticker] = data;
                updateMarketMapTile(ticker, data.change_pct);
            }
        } catch (e) {
            console.warn(`Failed to fetch map data for ${ticker}:`, e);
        }
        await new Promise(resolve => setTimeout(resolve, 150));
    }
}

// Update individual tile change text and background color class
function updateMarketMapTile(ticker, changePct) {
    const tile = document.querySelector(`.map-tile[data-ticker="${ticker}"]`);
    if (!tile) return;
    
    const changeEl = tile.querySelector('.tile-change');
    if (changeEl) {
        const sign = changePct >= 0 ? '+' : '';
        changeEl.textContent = `${sign}${changePct.toFixed(1)}%`;
    }
    
    tile.classList.remove('strong-up', 'mod-up', 'strong-down', 'mod-down', 'kr-strong-up', 'kr-mod-up', 'kr-strong-down', 'kr-mod-down', 'flat');
    tile.classList.add(getChangeClass(changePct));
}

// Helper to determine CSS class based on price performance and color mode
function getChangeClass(changePct) {
    if (mapColorMode === 'us') {
        if (changePct > 1.5) return 'strong-up';
        if (changePct > 0) return 'mod-up';
        if (changePct < -1.5) return 'strong-down';
        if (changePct < 0) return 'mod-down';
    } else {
        if (changePct > 1.5) return 'kr-strong-up';
        if (changePct > 0) return 'kr-mod-up';
        if (changePct < -1.5) return 'kr-strong-down';
        if (changePct < 0) return 'kr-mod-down';
    }
    return 'flat';
}

// Format font size based on box width
function getFontSize(w) {
    if (w > 80) return 0.85;
    if (w > 50) return 0.72;
    return 0.6;
}

// Format price with appropriate currency/yield prefixes and decimal places
function formatPrice(ticker, val) {
    if (val === null || val === undefined) return 'Loading...';
    const num = Number(val);
    if (ticker === '^TNX') {
        return `${num.toFixed(2)}%`;
    }
    if (ticker === 'KRW=X') {
        return `₩${num.toLocaleString('ko-KR', { maximumFractionDigits: 1 })}`;
    }
    if (ticker === 'GC=F' || ticker === 'CL=F' || ticker === 'BTC-USD' || ticker.startsWith('^')) {
        const decimals = (ticker === 'CL=F') ? 2 : (ticker === 'BTC-USD' ? 0 : 1);
        return num.toLocaleString('ko-KR', { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
    }
    return `$${num.toFixed(2)}`;
}
