/**
 * In-Page Search Widget
 * Drop this script into any static HTML page to add a Ctrl+F-style
 * search box near the top of the page.
 *
 * Usage: Add <script src="page-search.js"></script> just before </body>
 *        or anywhere after the content you want searchable.
 *
 * The widget auto-injects its own HTML/CSS. No dependencies.
 */
(function () {
  "use strict";

  // --- Configuration ---
  const HIGHLIGHT_CLASS = "psr-highlight";
  const ACTIVE_CLASS = "psr-highlight-active";
  const CONTAINER_ID = "psr-search-container";
  const MIN_QUERY_LENGTH = 2;

  // --- Inject CSS ---
  const style = document.createElement("style");
  style.textContent = `
    #${CONTAINER_ID} {
      position: sticky;
      top: 0;
      z-index: 9999;
      background: #003366;
      color: #fff;
      padding: 8px 16px;
      display: flex;
      align-items: center;
      gap: 10px;
      font-family: Arial, Helvetica, sans-serif;
      font-size: 14px;
      flex-wrap: wrap;
    }
    #${CONTAINER_ID} label {
      font-weight: bold;
      white-space: nowrap;
    }
    #psr-search-input {
      padding: 5px 8px;
      font-size: 14px;
      border: 1px solid #ccc;
      border-radius: 3px;
      width: 260px;
      max-width: 40vw;
    }
    #psr-search-input:focus {
      outline: 2px solid #d4a843;
      outline-offset: 1px;
    }
    #${CONTAINER_ID} button {
      padding: 5px 12px;
      font-size: 13px;
      cursor: pointer;
      border: 1px solid #ccc;
      border-radius: 3px;
      background: #d4a843;
      color: #1a3a5c;
      font-weight: bold;
    }
    #${CONTAINER_ID} button:hover {
      background: #c49a35;
    }
    #${CONTAINER_ID} button:focus {
      outline: 2px solid #fff;
      outline-offset: 1px;
    }
    #${CONTAINER_ID} button:disabled {
      opacity: 0.5;
      cursor: default;
    }
    #psr-match-count {
      white-space: nowrap;
      min-width: 90px;
    }
    .${HIGHLIGHT_CLASS} {
      background-color: #fff176;
      color: #000;
      border-radius: 2px;
      padding: 0 1px;
    }
    .${ACTIVE_CLASS} {
      background-color: #ff9800;
      color: #000;
      outline: 2px solid #e65100;
      border-radius: 2px;
    }
  `;
  document.head.appendChild(style);

  // --- Inject HTML ---
  const container = document.createElement("div");
  container.id = CONTAINER_ID;
  container.setAttribute("role", "search");
  container.setAttribute("aria-label", "Search within this page");
  container.innerHTML = `
    <label for="psr-search-input">Search this page:</label>
    <input type="text" id="psr-search-input" placeholder="Enter search term..."
           aria-describedby="psr-match-count">
    <button type="button" id="psr-btn-prev" aria-label="Previous match" disabled>&laquo; Prev</button>
    <button type="button" id="psr-btn-next" aria-label="Next match" disabled>Next &raquo;</button>
    <button type="button" id="psr-btn-clear" aria-label="Clear search">Clear</button>
    <span id="psr-match-count" aria-live="polite"></span>
  `;
  document.body.insertBefore(container, document.body.firstChild);

  // --- References ---
  const input = document.getElementById("psr-search-input");
  const btnPrev = document.getElementById("psr-btn-prev");
  const btnNext = document.getElementById("psr-btn-next");
  const btnClear = document.getElementById("psr-btn-clear");
  const matchCount = document.getElementById("psr-match-count");

  let highlights = [];
  let currentIndex = -1;

  // --- Functions ---

  /**
   * Remove all highlight <mark> elements and restore original text nodes.
   */
  function clearHighlights() {
    const marks = document.querySelectorAll("." + HIGHLIGHT_CLASS);
    marks.forEach(function (mark) {
      const parent = mark.parentNode;
      parent.replaceChild(document.createTextNode(mark.textContent), mark);
      parent.normalize(); // merge adjacent text nodes
    });
    highlights = [];
    currentIndex = -1;
    matchCount.textContent = "";
    btnPrev.disabled = true;
    btnNext.disabled = true;
  }

  /**
   * Walk text nodes under a root element, skipping the search container
   * and any existing highlight marks, script, and style elements.
   */
  function getTextNodes(root) {
    var nodes = [];
    var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode: function (node) {
        var parent = node.parentElement;
        if (!parent) return NodeFilter.FILTER_REJECT;
		/**
		* tell the tree walker to skip any text nodes inside the sidebar nav, 
		* so only the main content area gets searched and highlighted.
		*/
		if (parent.closest("#" + CONTAINER_ID)) return NodeFilter.FILTER_REJECT;
		if (parent.closest("nav.sidebar")) return NodeFilter.FILTER_REJECT;		
		
        var tag = parent.tagName.toLowerCase();
        if (tag === "script" || tag === "style" || tag === "noscript")
          return NodeFilter.FILTER_REJECT;
        if (parent.classList.contains(HIGHLIGHT_CLASS))
          return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_ACCEPT;
      },
    });
    while (walker.nextNode()) nodes.push(walker.currentNode);
    return nodes;
  }

  /**
   * Search the page for the query string, wrap matches in <mark> tags.
   */
  function doSearch(query) {
    clearHighlights();
    if (query.length < MIN_QUERY_LENGTH) {
      matchCount.textContent = query.length > 0 ? "Type at least 2 characters" : "";
      return;
    }

    var lowerQuery = query.toLowerCase();
    var textNodes = getTextNodes(document.body);

    textNodes.forEach(function (node) {
      var text = node.textContent;
      var lowerText = text.toLowerCase();
      var idx = lowerText.indexOf(lowerQuery);

      if (idx === -1) return;

      // We need to split this text node and wrap matches.
      // Collect all match positions first.
      var positions = [];
      var searchFrom = 0;
      while ((idx = lowerText.indexOf(lowerQuery, searchFrom)) !== -1) {
        positions.push(idx);
        searchFrom = idx + lowerQuery.length;
      }

      // Build replacement fragment
      var frag = document.createDocumentFragment();
      var cursor = 0;
      positions.forEach(function (pos) {
        // Text before match
        if (pos > cursor) {
          frag.appendChild(document.createTextNode(text.substring(cursor, pos)));
        }
        // The match
        var mark = document.createElement("mark");
        mark.className = HIGHLIGHT_CLASS;
        mark.textContent = text.substring(pos, pos + query.length);
        frag.appendChild(mark);
        cursor = pos + query.length;
      });
      // Remaining text
      if (cursor < text.length) {
        frag.appendChild(document.createTextNode(text.substring(cursor)));
      }

      node.parentNode.replaceChild(frag, node);
    });

    highlights = Array.from(document.querySelectorAll("." + HIGHLIGHT_CLASS));
    if (highlights.length > 0) {
      btnPrev.disabled = false;
      btnNext.disabled = false;
      goToMatch(0);
    } else {
      matchCount.textContent = "No matches found";
    }
  }

  /**
   * Scroll to and activate a match by index.
   */
  function goToMatch(index) {
    if (highlights.length === 0) return;

    // Remove active class from previous
    if (currentIndex >= 0 && currentIndex < highlights.length) {
      highlights[currentIndex].classList.remove(ACTIVE_CLASS);
    }

    currentIndex = index;
    highlights[currentIndex].classList.add(ACTIVE_CLASS);

    // Scroll into view with some top offset so sticky bar doesn't cover it
    highlights[currentIndex].scrollIntoView({ behavior: "smooth", block: "center" });

    matchCount.textContent =
      (currentIndex + 1) + " of " + highlights.length + " match" +
      (highlights.length !== 1 ? "es" : "");
  }

  // --- Event Listeners ---

  var searchTimer;
  input.addEventListener("input", function () {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(function () {
      doSearch(input.value.trim());
    }, 300);
  });

  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter") {
      e.preventDefault();
      if (highlights.length > 0) {
        if (e.shiftKey) {
          goToMatch(currentIndex <= 0 ? highlights.length - 1 : currentIndex - 1);
        } else {
          goToMatch(currentIndex >= highlights.length - 1 ? 0 : currentIndex + 1);
        }
      } else {
        doSearch(input.value.trim());
      }
    }
    if (e.key === "Escape") {
      clearHighlights();
      input.value = "";
      input.blur();
    }
  });

  btnNext.addEventListener("click", function () {
    if (highlights.length === 0) return;
    goToMatch(currentIndex >= highlights.length - 1 ? 0 : currentIndex + 1);
  });

  btnPrev.addEventListener("click", function () {
    if (highlights.length === 0) return;
    goToMatch(currentIndex <= 0 ? highlights.length - 1 : currentIndex - 1);
  });

  btnClear.addEventListener("click", function () {
    clearHighlights();
    input.value = "";
    input.focus();
  });
})();