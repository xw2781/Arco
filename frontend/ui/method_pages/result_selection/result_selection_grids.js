(function () {
  const parts = window.ResultSelectionParts || (window.ResultSelectionParts = {});

  parts.installGrids = function installGrids(ctx) {
    with (ctx) {
      const methodSpreadsheetTable = createSpreadsheetTableController({
        getRoot: () => els.methodGrid,
        getBounds: () => ({
          maxRow: getRowCount(),
          maxCol: buildMethodColumns(getDetails()).length - 1,
        }),
        readSelection: () => {
          const active = state.methodHighlight;
          return {
            ranges: normalizedMethodHighlightRanges().map((range) => ({
              r0: range.startRow,
              r1: range.endRow,
              c0: range.startCol,
              c1: range.endCol,
            })),
            activeCell: active ? { r: active.endRow, c: active.endCol } : null,
            anchorCell: active ? { r: active.startRow, c: active.startCol } : null,
          };
        },
        writeSelection: ({ ranges, activeCell, anchorCell }) => {
          const nextRanges = ranges.map((range) => ({
            startCol: range.c0,
            startRow: range.r0,
            endCol: range.c1,
            endRow: range.r1,
          }));
          state.methodHighlights = nextRanges;
          if (!nextRanges.length) {
            state.methodHighlight = null;
            return;
          }
          const range = nextRanges[nextRanges.length - 1];
          const anchor = anchorCell || { r: range.startRow, c: range.startCol };
          const active = activeCell || { r: range.endRow, c: range.endCol };
          state.methodHighlight = {
            startCol: anchor.c,
            startRow: anchor.r,
            endCol: active.c,
            endRow: active.r,
          };
        },
        cellSelector: "td.rsMethodCell[data-row-index][data-col-index]",
        rowHeaderSelector: "td.rsOriginCell[data-row-index]",
        columnHeaderSelector: "thead th[data-col-index]",
        getCellPosition: (cell) => ({
          r: Number(cell?.dataset?.rowIndex),
          c: Number(cell?.dataset?.colIndex),
        }),
        getRowHeaderIndex: (header) => Number(header?.dataset?.rowIndex),
        getColumnHeaderIndex: (header) => Number(header?.dataset?.colIndex),
        selectedClasses: ["rsHighlightedCell"],
        anchorClasses: ["rsHighlightAnchorCell", "arSpreadsheetSelectionAnchor"],
        rowSelectedLabelClasses: ["rsHighlightedRowLabel", "arSpreadsheetSelectedLabel"],
        columnSelectedLabelClasses: ["rsHighlightedColumnLabel", "arSpreadsheetSelectedLabel"],
        getCellValue: (_position, cell) => cell?.dataset?.copyValue ?? "",
        onAfterWrite: resetWeightEditSession,
        onAfterCopy: () => postStatus("Copied selected Result Selection values."),
        scrollCellIntoView: scrollMethodCellIntoView,
      });

      const resultsSpreadsheetTable = createSpreadsheetTableController({
        getRoot: () => els.resultsGrid,
        getBounds: () => ({
          maxRow: getRowCount(),
          maxCol: buildResultsColumns(getDetails()).length - 1,
        }),
        readSelection: () => {
          const highlight = state.resultsHighlight;
          if (!highlight) return { ranges: [], activeCell: null, anchorCell: null };
          return {
            ranges: [{
              r0: highlight.startRow,
              r1: highlight.endRow,
              c0: highlight.startCol,
              c1: highlight.endCol,
            }],
            activeCell: { r: highlight.endRow, c: highlight.endCol },
            anchorCell: { r: highlight.startRow, c: highlight.startCol },
          };
        },
        writeSelection: ({ ranges, activeCell, anchorCell }) => {
          const range = ranges[0];
          if (!range) {
            state.resultsHighlight = null;
            return;
          }
          const anchor = anchorCell || { r: range.r0, c: range.c0 };
          const active = activeCell || { r: range.r1, c: range.c1 };
          state.resultsHighlight = {
            startCol: anchor.c,
            startRow: anchor.r,
            endCol: active.c,
            endRow: active.r,
          };
        },
        cellSelector: "td.rsResultsCell[data-row-index][data-col-index]",
        rowHeaderSelector: "td.rsOriginCell[data-row-index]",
        columnHeaderSelector: "thead th[data-col-index]",
        getCellPosition: (cell) => ({
          r: Number(cell?.dataset?.rowIndex),
          c: Number(cell?.dataset?.colIndex),
        }),
        getRowHeaderIndex: (header) => Number(header?.dataset?.rowIndex),
        getColumnHeaderIndex: (header) => Number(header?.dataset?.colIndex),
        selectedClasses: ["rsHighlightedCell"],
        anchorClasses: ["rsHighlightAnchorCell", "arSpreadsheetSelectionAnchor"],
        rowSelectedLabelClasses: ["rsHighlightedRowLabel", "arSpreadsheetSelectedLabel"],
        columnSelectedLabelClasses: ["rsHighlightedColumnLabel", "arSpreadsheetSelectedLabel"],
        getCellValue: (_position, cell) => cell?.dataset?.copyValue ?? "",
        onAfterCopy: () => postStatus("Copied selected Result Selection values."),
        scrollCellIntoView: scrollResultsCellIntoView,
      });

      function isSourceCellSelectable(sourceIndex, rowIndex) {
        return numberOrNull(state.sources[sourceIndex]?.values?.[rowIndex]) !== null;
      }

      function isSourceCellSelected(sourceIndex, rowIndex) {
        const source = state.sources[sourceIndex];
        if (!source || !isSourceCellSelectable(sourceIndex, rowIndex)) return false;
        return Math.max(0, numberOrNull(source.weights?.[rowIndex]) ?? 0) > 0;
      }

      function syncSourceCellSelectionDom(sourceIndex, rowIndex) {
        const selector = `.rsSourceCell[data-source-index="${sourceIndex}"][data-row-index="${rowIndex}"]`;
        const cell = els.methodGrid?.querySelector?.(selector);
        if (cell) cell.classList.toggle("rsSelectedSourceCell", isSourceCellSelected(sourceIndex, rowIndex));
      }

      function setWeightValue(sourceIndex, rowIndex, rawValue) {
        const source = state.sources[sourceIndex];
        if (!source) return null;
        const weight = Math.max(0, numberOrNull(rawValue) ?? 0);
        while (source.weights.length <= rowIndex) source.weights.push(0);
        source.weights[rowIndex] = weight;
        syncSourceCellSelectionDom(sourceIndex, rowIndex);
        return weight;
      }

      function isUltimateOverridden(rowIndex) {
        return Object.prototype.hasOwnProperty.call(state.ultimateOverrides, rowIndex)
          && numberOrNull(state.ultimateOverrides[rowIndex]) !== null;
      }

      function calculatedSelectedUltimateAt(rowIndex) {
        let numerator = 0;
        let denominator = 0;
        for (let sourceIndex = 0; sourceIndex < state.sources.length; sourceIndex += 1) {
          const source = state.sources[sourceIndex];
          const value = numberOrNull(source.values[rowIndex]);
          const weight = Math.max(0, numberOrNull(source.weights[rowIndex]) ?? 0);
          if (value === null || weight <= 0 || !isSourceCellSelected(sourceIndex, rowIndex)) continue;
          numerator += value * weight;
          denominator += weight;
        }
        return denominator > 0 ? numerator / denominator : null;
      }

      function setUltimateOverride(rowIndex, rawValue) {
        // Excel copies displayed text, so "46,759" arrives with thousands separators.
        const value = numberOrNull(String(rawValue ?? "").replace(/,/g, "").trim());
        if (value === null) return false;
        state.ultimateOverrides[rowIndex] = value;
        return true;
      }

      function clearUltimateOverride(rowIndex) {
        if (!isUltimateOverridden(rowIndex)) return false;
        delete state.ultimateOverrides[rowIndex];
        return true;
      }

      function isMethodDataRow(rowIndex) {
        return rowIndex >= 0 && rowIndex < getRowCount();
      }

      function applyHighlightedUltimateValue(rawValue) {
        const columns = buildMethodColumns(getDetails());
        let changed = false;
        forEachHighlightedMethodCell((column, rowIndex) => {
          if (column?.type !== "ultimate") return;
          if (setUltimateOverride(rowIndex, rawValue)) changed = true;
        }, columns);
        return changed;
      }

      function highlightedHasWeightTargets(highlight = null) {
        const columns = buildMethodColumns(getDetails());
        const ranges = highlight ? [highlight] : normalizedMethodHighlightRanges();
        for (const range of ranges) {
          for (let rowIndex = range.startRow; rowIndex <= range.endRow; rowIndex += 1) {
            if (!isMethodDataRow(rowIndex)) continue;
            for (let colIndex = range.startCol; colIndex <= range.endCol; colIndex += 1) {
              const column = columns[colIndex];
              if (column?.type === "weight") return true;
              if (column?.type === "source" && isSourceCellSelectable(column.sourceIndex, rowIndex)) return true;
            }
          }
        }
        return false;
      }

      function highlightedHasUltimateCells(highlight = null) {
        const columns = buildMethodColumns(getDetails());
        const ranges = highlight ? [highlight] : normalizedMethodHighlightRanges();
        for (const range of ranges) {
          for (let rowIndex = range.startRow; rowIndex <= range.endRow; rowIndex += 1) {
            if (!isMethodDataRow(rowIndex)) continue;
            for (let colIndex = range.startCol; colIndex <= range.endCol; colIndex += 1) {
              if (columns[colIndex]?.type === "ultimate") return true;
            }
          }
        }
        return false;
      }

      function forEachHighlightedMethodCell(callback, columns = buildMethodColumns(getDetails()), ranges = normalizedMethodHighlightRanges()) {
        let visited = null;
        for (const range of ranges) {
          for (let rowIndex = range.startRow; rowIndex <= range.endRow; rowIndex += 1) {
            if (!isMethodDataRow(rowIndex)) continue;
            for (let colIndex = range.startCol; colIndex <= range.endCol; colIndex += 1) {
              const key = `${colIndex}:${rowIndex}`;
              if (visited?.has(key)) continue;
              if (!visited) visited = new Set();
              visited.add(key);
              callback(columns[colIndex], rowIndex, colIndex, range);
            }
          }
        }
      }

      function forEachHighlightedMethodRangeCell(range, callback, columns = buildMethodColumns(getDetails())) {
        if (!range) return;
        for (let rowIndex = range.startRow; rowIndex <= range.endRow; rowIndex += 1) {
          if (!isMethodDataRow(rowIndex)) continue;
          for (let colIndex = range.startCol; colIndex <= range.endCol; colIndex += 1) {
            const column = columns[colIndex];
            callback(column, rowIndex, colIndex);
          }
        }
      }

      function visibleWeightSourceIndices() {
        return buildMethodColumns(getDetails())
          .filter((column) => column.type === "weight")
          .map((column) => column.sourceIndex);
      }

      function applyWeightPaste(startSourceIndex, startRow, rawText) {
        const sourceIndices = visibleWeightSourceIndices();
        const startCol = sourceIndices.indexOf(startSourceIndex);
        if (startCol < 0) return false;
        const rows = String(rawText ?? "")
          .replace(/\r\n/g, "\n")
          .replace(/\r/g, "\n")
          .split("\n");
        if (rows.length > 1 && rows[rows.length - 1] === "") rows.pop();
        let changed = false;
        const rowCount = getRowCount();
        rows.forEach((rowText, rowOffset) => {
          const targetRow = startRow + rowOffset;
          if (targetRow >= rowCount) return;
          rowText.split("\t").forEach((cellText, colOffset) => {
            const sourceIndex = sourceIndices[startCol + colOffset];
            if (sourceIndex === undefined) return;
            setWeightValue(sourceIndex, targetRow, cellText);
            changed = true;
          });
        });
        return changed;
      }

      function applyHighlightedWeightValue(rawValue) {
        const columns = buildMethodColumns(getDetails());
        let changed = false;
        forEachHighlightedMethodCell((column, rowIndex) => {
          if (!column || (column.type !== "weight" && column.type !== "source")) return;
          if (column.type === "source" && !isSourceCellSelectable(column.sourceIndex, rowIndex)) return;
          setWeightValue(column.sourceIndex, rowIndex, rawValue);
          changed = true;
        }, columns);
        return changed;
      }

      function parseClipboardGrid(rawText) {
        const rows = String(rawText ?? "")
          .replace(/\r\n/g, "\n")
          .replace(/\r/g, "\n")
          .split("\n");
        if (rows.length > 1 && rows[rows.length - 1] === "") rows.pop();
        return rows.map((row) => row.split("\t"));
      }

      function clipboardGridValue(grid, rowOffset, colOffset) {
        if (!grid.length) return "";
        if (grid.length === 1 && grid[0].length === 1) return grid[0][0] ?? "";
        return grid[rowOffset]?.[colOffset] ?? "";
      }

      function clipboardGridColumnCount(grid) {
        return grid.reduce((max, row) => Math.max(max, row.length), 0);
      }

      function pasteTargetEndRow(highlight, grid) {
        return Math.max(highlight.endRow, highlight.startRow + Math.max(1, grid.length) - 1);
      }

      function pasteTargetEndCol(highlight, grid) {
        return Math.max(highlight.endCol, highlight.startCol + Math.max(1, clipboardGridColumnCount(grid)) - 1);
      }

      function applyHighlightedWeightGrid(grid) {
        const h = normalizedMethodHighlight();
        if (!h) return false;
        const columns = buildMethodColumns(getDetails());
        let changed = false;
        const endRow = pasteTargetEndRow(h, grid);
        const endCol = pasteTargetEndCol(h, grid);
        forEachHighlightedMethodRangeCell({ ...h, endRow, endCol }, (column, rowIndex, colIndex) => {
          if (!column || (column.type !== "weight" && column.type !== "source")) return;
          if (column.type === "source" && !isSourceCellSelectable(column.sourceIndex, rowIndex)) return;
          setWeightValue(column.sourceIndex, rowIndex, clipboardGridValue(grid, rowIndex - h.startRow, colIndex - h.startCol));
          changed = true;
        }, columns);
        return changed;
      }

      function applyHighlightedUltimateGrid(grid) {
        const h = normalizedMethodHighlight();
        if (!h) return false;
        const columns = buildMethodColumns(getDetails());
        let changed = false;
        const endRow = pasteTargetEndRow(h, grid);
        const endCol = pasteTargetEndCol(h, grid);
        forEachHighlightedMethodRangeCell({ ...h, endRow, endCol }, (column, rowIndex, colIndex) => {
          if (column?.type !== "ultimate") return;
          if (setUltimateOverride(rowIndex, clipboardGridValue(grid, rowIndex - h.startRow, colIndex - h.startCol))) changed = true;
        }, columns);
        return changed;
      }

      function applyHighlightedPasteText(rawText) {
        const h = normalizedMethodHighlight();
        if (!h) return false;
        resetWeightEditSession();
        const grid = parseClipboardGrid(rawText);
        if (highlightedHasWeightTargets(h)) return applyHighlightedWeightGrid(grid);
        if (highlightedHasUltimateCells(h)) return applyHighlightedUltimateGrid(grid);
        return false;
      }

      function methodHighlightSessionKey(highlight = normalizedMethodHighlight()) {
        const ranges = highlight ? [highlight] : normalizedMethodHighlightRanges();
        if (!ranges.length) return "";
        return ranges
          .map((range) => `${range.startCol}:${range.startRow}:${range.endCol}:${range.endRow}`)
          .join("|");
      }

      function resetWeightEditSession() {
        state.weightEditSession = null;
      }

      function applyHighlightedWeightKey(key) {
        const h = normalizedMethodHighlight();
        if (!h || !/^[0-9.]$/.test(key || "")) return false;
        const sessionKey = methodHighlightSessionKey(h);
        const current = state.weightEditSession?.key === sessionKey ? state.weightEditSession.value : "";
        if (key === "." && current.includes(".")) return false;
        const nextValue = current
          ? `${current}${key}`
          : key === "."
            ? "0."
            : key;
        state.weightEditSession = { key: sessionKey, value: nextValue };
        if (highlightedHasWeightTargets()) {
          if (applyHighlightedWeightValue(nextValue)) return true;
        } else if (highlightedHasUltimateCells()) {
          if (applyHighlightedUltimateValue(nextValue)) return true;
        }
        resetWeightEditSession();
        return false;
      }

      function normalizedMethodHighlight() {
        const h = normalizeMethodHighlightRange(state.methodHighlight);
        if (h) return h;
        return normalizedMethodHighlightRanges()[0] || null;
      }

      function normalizeMethodHighlightRange(h) {
        if (!h) return null;
        return {
          startRow: Math.min(h.startRow, h.endRow),
          endRow: Math.max(h.startRow, h.endRow),
          startCol: Math.min(h.startCol, h.endCol),
          endCol: Math.max(h.startCol, h.endCol),
        };
      }

      function rawMethodHighlightRanges() {
        const ranges = Array.isArray(state.methodHighlights) ? state.methodHighlights : [];
        if (ranges.length) return ranges;
        return state.methodHighlight ? [state.methodHighlight] : [];
      }

      function normalizedMethodHighlightRanges() {
        return rawMethodHighlightRanges()
          .map((range) => normalizeMethodHighlightRange(range))
          .filter(Boolean);
      }

      function rangesEqual(a, b) {
        const left = normalizeMethodHighlightRange(a);
        const right = normalizeMethodHighlightRange(b);
        return !!left && !!right
          && left.startCol === right.startCol
          && left.startRow === right.startRow
          && left.endCol === right.endCol
          && left.endRow === right.endRow;
      }

      function setMethodHighlightRanges(ranges, activeRange = null) {
        const next = (Array.isArray(ranges) ? ranges : [])
          .map((range) => normalizeMethodHighlightRange(range))
          .filter(Boolean);
        state.methodHighlights = next;
        state.methodHighlight = activeRange
          ? normalizeMethodHighlightRange(activeRange)
          : next.length
            ? next[next.length - 1]
            : null;
      }

      function isTextEntryTarget(target) {
        return !!target?.closest?.("input,textarea,select,[contenteditable='true']");
      }

      function isMethodCellHighlighted(colIndex, rowIndex) {
        return normalizedMethodHighlightRanges().some((h) => (
          rowIndex >= h.startRow
          && rowIndex <= h.endRow
          && colIndex >= h.startCol
          && colIndex <= h.endCol
        ));
      }

      function isMethodColumnHighlighted(colIndex) {
        return normalizedMethodHighlightRanges().some((h) => colIndex >= h.startCol && colIndex <= h.endCol);
      }

      function isMethodRowHighlightedByRange(rowIndex) {
        return normalizedMethodHighlightRanges().some((h) => rowIndex >= h.startRow && rowIndex <= h.endRow);
      }

      function isMethodHighlightAnchor(colIndex, rowIndex) {
        const h = state.methodHighlight;
        return !!h && h.startCol === colIndex && h.startRow === rowIndex;
      }

      function normalizedResultsHighlight() {
        const h = state.resultsHighlight;
        if (!h) return null;
        return {
          startRow: Math.min(h.startRow, h.endRow),
          endRow: Math.max(h.startRow, h.endRow),
          startCol: Math.min(h.startCol, h.endCol),
          endCol: Math.max(h.startCol, h.endCol),
        };
      }

      function isResultsCellHighlighted(colIndex, rowIndex) {
        const h = normalizedResultsHighlight();
        return !!h
          && rowIndex >= h.startRow
          && rowIndex <= h.endRow
          && colIndex >= h.startCol
          && colIndex <= h.endCol;
      }

      function isResultsColumnHighlighted(colIndex) {
        const h = normalizedResultsHighlight();
        return !!h && colIndex >= h.startCol && colIndex <= h.endCol;
      }

      function isResultsRowHighlightedByRange(rowIndex) {
        const h = normalizedResultsHighlight();
        return !!h && rowIndex >= h.startRow && rowIndex <= h.endRow;
      }

      function isResultsHighlightAnchor(colIndex, rowIndex) {
        const h = state.resultsHighlight;
        return !!h && h.startCol === colIndex && h.startRow === rowIndex;
      }

      function setMethodHighlight(startCol, startRow, endCol = startCol, endRow = startRow) {
        methodSpreadsheetTable.setRange(
          { r: startRow, c: startCol },
          { r: endRow, c: endCol },
        );
      }

      function setResultsHighlight(startCol, startRow, endCol = startCol, endRow = startRow) {
        resultsSpreadsheetTable.setRange(
          { r: startRow, c: startCol },
          { r: endRow, c: endCol },
        );
      }

      function removeMethodHighlights() {
        state.methodHighlightDragging = false;
        methodSpreadsheetTable.clear();
      }

      function removeResultsHighlights() {
        state.resultsHighlightDragging = false;
        resultsSpreadsheetTable.clear();
      }

      function normalizeMethodHighlight(columns = buildMethodColumns(getDetails()), rowCount = getRowCount()) {
        const rawRanges = rawMethodHighlightRanges();
        if (!rawRanges.length) return;
        const maxCol = Math.max(0, columns.length - 1);
        const maxRow = Math.max(0, rowCount - 1);
        const nextRanges = rawRanges.map((h) => ({
          startCol: Math.max(0, Math.min(maxCol, h.startCol)),
          startRow: Math.max(0, Math.min(maxRow, h.startRow)),
          endCol: Math.max(0, Math.min(maxCol, h.endCol)),
          endRow: Math.max(0, Math.min(maxRow, h.endRow)),
        }));
        const active = state.methodHighlight;
        const nextActive = active ? {
          startCol: Math.max(0, Math.min(maxCol, active.startCol)),
          startRow: Math.max(0, Math.min(maxRow, active.startRow)),
          endCol: Math.max(0, Math.min(maxCol, active.endCol)),
          endRow: Math.max(0, Math.min(maxRow, active.endRow)),
        } : nextRanges[nextRanges.length - 1];
        const changed = rawRanges.length !== nextRanges.length
          || rawRanges.some((h, index) => !rangesEqual(h, nextRanges[index]))
          || !rangesEqual(active, nextActive);
        if (changed) {
          resetWeightEditSession();
          setMethodHighlightRanges(nextRanges, nextActive);
        }
      }

      function normalizeResultsHighlight(columns = buildResultsColumns(getDetails()), rowCount = getRowCount()) {
        const h = state.resultsHighlight;
        if (!h) return;
        const maxCol = Math.max(0, columns.length - 1);
        const maxRow = Math.max(0, rowCount - 1);
        const next = {
          startCol: Math.max(0, Math.min(maxCol, h.startCol)),
          startRow: Math.max(0, Math.min(maxRow, h.startRow)),
          endCol: Math.max(0, Math.min(maxCol, h.endCol)),
          endRow: Math.max(0, Math.min(maxRow, h.endRow)),
        };
        const changed = h.startCol !== next.startCol
          || h.startRow !== next.startRow
          || h.endCol !== next.endCol
          || h.endRow !== next.endRow;
        if (changed) state.resultsHighlight = next;
      }

      function setMethodRowHighlight(rowIndex, columnCount) {
        methodSpreadsheetTable.selectRow(rowIndex);
      }

      function setMethodColumnHighlight(colIndex, rowCount) {
        methodSpreadsheetTable.selectColumn(colIndex);
      }

      function setResultsRowHighlight(rowIndex, columnCount) {
        resultsSpreadsheetTable.selectRow(rowIndex);
      }

      function setResultsColumnHighlight(colIndex, rowCount) {
        resultsSpreadsheetTable.selectColumn(colIndex);
      }

      function isNavigableMethodColumn(column) {
        return !!column && column.type !== "spacer";
      }

      function nextNavigableMethodColumnIndex(columns, colIndex, deltaCol) {
        for (let nextCol = colIndex + deltaCol; nextCol >= 0 && nextCol < columns.length; nextCol += deltaCol) {
          if (isNavigableMethodColumn(columns[nextCol])) return nextCol;
        }
        return colIndex;
      }

      function focusResultsGrid() {
        if (!els.resultsGrid) return;
        try {
          els.resultsGrid.focus({ preventScroll: true });
        } catch {
          els.resultsGrid.focus?.();
        }
      }

      function scrollMethodCellIntoView({ r, c }) {
        const cell = Array.from(els.methodGrid?.querySelectorAll?.(".rsMethodCell") || [])
          .find((td) => Number(td.dataset.colIndex) === c && Number(td.dataset.rowIndex) === r);
        if (!cell) return;
        const host = els.methodGrid?.closest?.(".rsGridHost");
        const header = els.methodGrid?.querySelector?.("thead");
        if (!host) {
          cell.scrollIntoView?.({ block: "nearest", inline: "nearest" });
          return;
        }
        const hostRect = host.getBoundingClientRect();
        const cellRect = cell.getBoundingClientRect();
        const headerHeight = Math.ceil(header?.getBoundingClientRect?.().height || 0);
        const visibleTop = hostRect.top + headerHeight;
        const visibleBottom = hostRect.bottom;
        const visibleLeft = hostRect.left;
        const visibleRight = hostRect.right;
        if (cellRect.top < visibleTop) {
          host.scrollTop += cellRect.top - visibleTop;
        } else if (cellRect.bottom > visibleBottom) {
          host.scrollTop += cellRect.bottom - visibleBottom;
        }
        if (cellRect.left < visibleLeft) {
          host.scrollLeft += cellRect.left - visibleLeft;
        } else if (cellRect.right > visibleRight) {
          host.scrollLeft += cellRect.right - visibleRight;
        }
      }

      function scrollMethodHighlightAnchorIntoView() {
        const active = methodSpreadsheetTable.selection().activeCell;
        if (active) scrollMethodCellIntoView(active);
      }

      function scrollResultsCellIntoView({ r, c }) {
        const cell = Array.from(els.resultsGrid?.querySelectorAll?.(".rsResultsCell") || [])
          .find((td) => Number(td.dataset.colIndex) === c && Number(td.dataset.rowIndex) === r);
        if (!cell) return;
        const host = els.resultsGrid?.closest?.(".rsGridHost");
        const header = els.resultsGrid?.querySelector?.("thead");
        if (!host) {
          cell.scrollIntoView?.({ block: "nearest", inline: "nearest" });
          return;
        }
        const hostRect = host.getBoundingClientRect();
        const cellRect = cell.getBoundingClientRect();
        const headerHeight = Math.ceil(header?.getBoundingClientRect?.().height || 0);
        const visibleTop = hostRect.top + headerHeight;
        const visibleBottom = hostRect.bottom;
        const visibleLeft = hostRect.left;
        const visibleRight = hostRect.right;
        if (cellRect.top < visibleTop) {
          host.scrollTop += cellRect.top - visibleTop;
        } else if (cellRect.bottom > visibleBottom) {
          host.scrollTop += cellRect.bottom - visibleBottom;
        }
        if (cellRect.left < visibleLeft) {
          host.scrollLeft += cellRect.left - visibleLeft;
        } else if (cellRect.right > visibleRight) {
          host.scrollLeft += cellRect.right - visibleRight;
        }
      }

      function scrollResultsHighlightAnchorIntoView() {
        const active = resultsSpreadsheetTable.selection().activeCell;
        if (active) scrollResultsCellIntoView(active);
      }

      function moveMethodHighlight(deltaCol, deltaRow) {
        const raw = state.methodHighlight;
        const h = normalizedMethodHighlight();
        if (!raw || !h || state.activeTab !== "method") return false;
        const columns = buildMethodColumns(getDetails());
        if (!columns.length) return false;

        const maxRow = Math.max(0, getRowCount());
        const height = h.endRow - h.startRow;
        const maxStartRow = Math.max(0, maxRow - height);
        const nextStartRow = Math.max(0, Math.min(maxStartRow, h.startRow + deltaRow));

        const width = h.endCol - h.startCol;
        let nextStartCol = h.startCol;
        if (deltaCol !== 0 && width === 0) {
          nextStartCol = nextNavigableMethodColumnIndex(columns, h.startCol, deltaCol);
        } else if (deltaCol !== 0) {
          const maxStartCol = Math.max(0, columns.length - 1 - width);
          nextStartCol = Math.max(0, Math.min(maxStartCol, h.startCol + deltaCol));
        }

        const actualDeltaCol = nextStartCol - h.startCol;
        const actualDeltaRow = nextStartRow - h.startRow;
        if (actualDeltaCol || actualDeltaRow) {
          resetWeightEditSession();
          const nextRaw = {
            startCol: raw.startCol + actualDeltaCol,
            startRow: raw.startRow + actualDeltaRow,
            endCol: raw.endCol + actualDeltaCol,
            endRow: raw.endRow + actualDeltaRow,
          };
          const ranges = normalizedMethodHighlightRanges();
          const nextRanges = ranges.map((range) => rangesEqual(range, raw) ? nextRaw : range);
          if (!nextRanges.some((range) => rangesEqual(range, nextRaw))) nextRanges.push(nextRaw);
          setMethodHighlightRanges(nextRanges, nextRaw);
          normalizeMethodHighlight(columns, maxRow + 1);
          applyMethodHighlightDom();
          scrollMethodHighlightAnchorIntoView();
        }
        return true;
      }

      function moveResultsHighlight(deltaCol, deltaRow) {
        const raw = state.resultsHighlight;
        const h = normalizedResultsHighlight();
        if (!raw || !h || state.activeTab !== "results") return false;
        const columns = buildResultsColumns(getDetails());
        if (!columns.length) return false;

        const maxRow = Math.max(0, getRowCount());
        const height = h.endRow - h.startRow;
        const maxStartRow = Math.max(0, maxRow - height);
        const nextStartRow = Math.max(0, Math.min(maxStartRow, h.startRow + deltaRow));

        const width = h.endCol - h.startCol;
        let nextStartCol = h.startCol;
        if (deltaCol !== 0 && width === 0) {
          nextStartCol = nextNavigableMethodColumnIndex(columns, h.startCol, deltaCol);
        } else if (deltaCol !== 0) {
          const maxStartCol = Math.max(0, columns.length - 1 - width);
          nextStartCol = Math.max(0, Math.min(maxStartCol, h.startCol + deltaCol));
        }

        const actualDeltaCol = nextStartCol - h.startCol;
        const actualDeltaRow = nextStartRow - h.startRow;
        if (actualDeltaCol || actualDeltaRow) {
          state.resultsHighlight = {
            startCol: raw.startCol + actualDeltaCol,
            startRow: raw.startRow + actualDeltaRow,
            endCol: raw.endCol + actualDeltaCol,
            endRow: raw.endRow + actualDeltaRow,
          };
          normalizeResultsHighlight(columns, maxRow + 1);
          applyResultsHighlightDom();
          scrollResultsHighlightAnchorIntoView();
        }
        return true;
      }

      function handleMethodHighlightArrowKey(event) {
        const deltas = {
          ArrowLeft: [-1, 0],
          ArrowRight: [1, 0],
          ArrowUp: [0, -1],
          ArrowDown: [0, 1],
        };
        const delta = deltas[event.key];
        if (state.activeTab !== "method" || !delta || event.altKey || isTextEntryTarget(event.target)) return false;
        if (!normalizedMethodHighlight()) return false;
        const settings = {
          extend: event.shiftKey,
          jump: event.ctrlKey || event.metaKey,
        };
        if (!methodSpreadsheetTable.move(delta[1], delta[0], settings)) return false;
        while (!settings.extend) {
          const active = methodSpreadsheetTable.selection().activeCell;
          if (!active || buildMethodColumns(getDetails())[active.c]?.type !== "spacer") break;
          if (!methodSpreadsheetTable.move(delta[1], delta[0], settings)) break;
        }
        event.preventDefault();
        event.stopPropagation();
        return true;
      }

      function handleResultsHighlightArrowKey(event) {
        const deltas = {
          ArrowLeft: [-1, 0],
          ArrowRight: [1, 0],
          ArrowUp: [0, -1],
          ArrowDown: [0, 1],
        };
        const delta = deltas[event.key];
        if (state.activeTab !== "results" || !delta || event.altKey || isTextEntryTarget(event.target)) return false;
        if (!normalizedResultsHighlight()) return false;
        const settings = {
          extend: event.shiftKey,
          jump: event.ctrlKey || event.metaKey,
        };
        if (!resultsSpreadsheetTable.move(delta[1], delta[0], settings)) return false;
        while (!settings.extend) {
          const active = resultsSpreadsheetTable.selection().activeCell;
          if (!active || buildResultsColumns(getDetails())[active.c]?.type !== "spacer") break;
          if (!resultsSpreadsheetTable.move(delta[1], delta[0], settings)) break;
        }
        event.preventDefault();
        event.stopPropagation();
        return true;
      }

      function applyMethodHighlightDom() {
        methodSpreadsheetTable.applyDom();
      }

      function applyResultsHighlightDom() {
        resultsSpreadsheetTable.applyDom();
      }

      function startMethodCellHighlight(event, colIndex, rowIndex, options = {}) {
        if (event.button !== 0) return;
        if (!options.preserveDefault) event.preventDefault();
        closeCellContextMenu();
        if (event.shiftKey) {
          methodSpreadsheetTable.selectCell({ r: rowIndex, c: colIndex }, { extend: true });
          focusMethodGrid();
          return;
        }
        state.methodHighlightDragging = true;
        methodSpreadsheetTable.selectCell({ r: rowIndex, c: colIndex });
        focusMethodGrid();
        const onUp = () => {
          state.methodHighlightDragging = false;
          document.removeEventListener("mouseup", onUp, true);
        };
        document.addEventListener("mouseup", onUp, true);
      }

      function startResultsCellHighlight(event, colIndex, rowIndex) {
        if (event.button !== 0) return;
        event.preventDefault();
        closeCellContextMenu();
        closeSourceContextMenu();
        state.resultsHighlightDragging = true;
        resultsSpreadsheetTable.selectCell({ r: rowIndex, c: colIndex }, { extend: event.shiftKey });
        focusResultsGrid();
        const onUp = () => {
          state.resultsHighlightDragging = false;
          document.removeEventListener("mouseup", onUp, true);
        };
        document.addEventListener("mouseup", onUp, true);
      }

      function extendMethodCellHighlight(colIndex, rowIndex) {
        if (!state.methodHighlightDragging || !state.methodHighlight) return;
        const anchor = methodSpreadsheetTable.selection().anchorCell;
        if (anchor) methodSpreadsheetTable.setRange(anchor, { r: rowIndex, c: colIndex });
      }

      function extendResultsCellHighlight(colIndex, rowIndex) {
        if (!state.resultsHighlightDragging || !state.resultsHighlight) return;
        const anchor = resultsSpreadsheetTable.selection().anchorCell;
        if (anchor) resultsSpreadsheetTable.setRange(anchor, { r: rowIndex, c: colIndex });
      }

      function selectedUltimateAt(rowIndex) {
        if (isUltimateOverridden(rowIndex)) return numberOrNull(state.ultimateOverrides[rowIndex]);
        return calculatedSelectedUltimateAt(rowIndex);
      }

      function firstTriangleSource() {
        const entry = orderedSourceEntries().find((item) => item.section === "triangle");
        return entry ? state.sources[entry.index] : null;
      }

      function hasLoadedTriangleSource() {
        return !!firstTriangleSource();
      }

      function latestDevelopedAt(rowIndex) {
        return numberOrNull(firstTriangleSource()?.values?.[rowIndex]);
      }

      function reserveAt(rowIndex, ultimateValue = selectedUltimateAt(rowIndex)) {
        const ultimate = numberOrNull(ultimateValue);
        if (ultimate === null) return null;
        const latestDeveloped = latestDevelopedAt(rowIndex);
        // An origin period with nothing developed yet has paid or reported
        // nothing, so the whole selected ultimate is still outstanding.
        return latestDeveloped === null ? ultimate : ultimate - latestDeveloped;
      }

      function effectiveWeightAt(sourceIndex, rowIndex) {
        const target = state.sources[sourceIndex];
        const targetValue = numberOrNull(target?.values?.[rowIndex]);
        if (targetValue === null) return null;
        const targetWeight = Math.max(0, numberOrNull(target?.weights?.[rowIndex]) ?? 0);
        let denominator = 0;
        for (let idx = 0; idx < state.sources.length; idx += 1) {
          const source = state.sources[idx];
          const value = numberOrNull(source.values[rowIndex]);
          const weight = Math.max(0, numberOrNull(source.weights[rowIndex]) ?? 0);
          if (value === null || weight <= 0 || !isSourceCellSelected(idx, rowIndex)) continue;
          denominator += weight;
        }
        if (denominator <= 0) return 0;
        return targetWeight > 0 && isSourceCellSelected(sourceIndex, rowIndex) ? targetWeight / denominator : 0;
      }

      function selectedUltimateVector() {
        const count = getRowCount();
        const out = [];
        for (let i = 0; i < count; i += 1) out.push(selectedUltimateAt(i));
        return out;
      }

      function calculatedUltimateVector() {
        const count = getRowCount();
        const out = [];
        for (let i = 0; i < count; i += 1) out.push(calculatedSelectedUltimateAt(i));
        return out;
      }

      function fmtNumber(value) {
        const n = numberOrNull(value);
        if (n === null) return "";
        return Math.round(n).toLocaleString();
      }

      function fmtRatio(value) {
        const n = numberOrNull(value);
        if (n === null) return "";
        const decimals = getDetails().statisticDecimalPlaces;
        if (getDetails().showRatiosAsPercentages) return `${(n * 100).toFixed(decimals)}%`;
        return n.toFixed(decimals);
      }

      function fmtEffectiveWeight(value, details = getDetails()) {
        const n = numberOrNull(value);
        if (n === null) return "";
        return `${(n * 100).toFixed(details.statisticDecimalPlaces)}%`;
      }

      function fmtWeightValue(value) {
        const n = numberOrNull(value);
        if (n === null) return "0.0";
        return n.toFixed(1);
      }

      function applyWeightValueClass(cell, value) {
        const n = numberOrNull(value) ?? 0;
        cell?.classList.toggle("rsWeightZero", n === 0);
        cell?.classList.toggle("rsWeightNonZero", n !== 0);
      }

      function methodColumnId(type, index = "") {
        return index === "" ? type : `${type}:${index}`;
      }

      function sourceMethodSection(source) {
        return norm(source?.dataFormat) === "triangle" ? "triangle" : "vector";
      }

      function sourceMethodSectionOrder(section) {
        return section === "triangle" ? 0 : 1;
      }

      function orderedSourceEntries() {
        return state.sources
          .map((source, index) => ({ source, index, section: sourceMethodSection(source) }))
          .sort((left, right) => {
            const sectionDelta = sourceMethodSectionOrder(left.section) - sourceMethodSectionOrder(right.section);
            if (sectionDelta) return sectionDelta;
            const nameDelta = compareSourceNames(left.source, right.source);
            return nameDelta || left.index - right.index;
          });
      }

      function appendSourceColumns(columns, entries, details, section) {
        entries.forEach(({ source, index }) => {
          columns.push({
            id: methodColumnId("source", index),
            type: "source",
            section,
            sourceIndex: index,
            label: source.name || `Source ${index + 1}`,
            className: "rsSourceHeader",
          });
          if (details.showWeights) {
            columns.push({
              id: methodColumnId("weight", index),
              type: "weight",
              section,
              sourceIndex: index,
              label: state.showEffectiveWeights ? "Weight %" : "Weight",
              className: "rsWeightHeader",
            });
          }
        });
      }

      function appendMethodSectionSpacer(columns, id) {
        columns.push({
          id: methodColumnId("spacer", id),
          type: "spacer",
          section: "spacer",
          label: "",
          className: "rsSectionSpacerHeader",
        });
      }

      function ratioStatisticLabel(details = {}) {
        const category = text(details.outputCategory || getOutputCategory()).toLowerCase();
        const basis = text(details.ratioBasis).toLowerCase();
        return category.includes("count") && basis.includes("exposure") ? "Frequency" : "Ultimate / Basis";
      }

      function appendStatisticColumns(columns, details, options = {}) {
        columns.push({
          id: methodColumnId("ultimate"),
          type: "ultimate",
          section: "stats",
          label: "Selected Ultimate",
          className: "rsUltimateHeader",
        });
        if (options.includeReserve) {
          columns.push({
            id: methodColumnId("reserve"),
            type: "reserve",
            section: "stats",
            label: "Reserve",
            className: "rsReserveHeader",
          });
        }
        if (details.ratioBasis) {
          columns.push({
            id: methodColumnId("ratio"),
            type: "ratio",
            section: "stats",
            label: ratioStatisticLabel(details),
            className: "rsRatioHeader",
          });
        }
      }

      function buildMethodColumns(details) {
        const columns = [{
          id: methodColumnId("origin"),
          type: "origin",
          section: "origin",
          label: getDatasetOriginLabelText(details.originLength),
          className: "rsOriginHeader",
        }];
        const entries = orderedSourceEntries();
        const triangleEntries = entries.filter((entry) => entry.section === "triangle");
        const vectorEntries = entries.filter((entry) => entry.section === "vector");
        appendSourceColumns(columns, triangleEntries, details, "triangle");
        if (triangleEntries.length && vectorEntries.length) appendMethodSectionSpacer(columns, "triangle-vector");
        appendSourceColumns(columns, vectorEntries, details, "vector");
        if (triangleEntries.length || vectorEntries.length) appendMethodSectionSpacer(columns, "sources-stats");
        appendStatisticColumns(columns, details, { includeReserve: triangleEntries.length > 0 });
        return columns;
      }

      function buildResultsColumns(details) {
        const columns = [{
          id: methodColumnId("origin"),
          type: "origin",
          section: "origin",
          label: getDatasetOriginLabelText(details.originLength),
          className: "rsOriginHeader",
        }];
        const triangleEntries = orderedSourceEntries().filter((entry) => entry.section === "triangle");
        appendSourceColumns(columns, triangleEntries, { showWeights: false }, "triangle");
        if (triangleEntries.length) appendMethodSectionSpacer(columns, "triangles-stats");
        appendStatisticColumns(columns, details, { includeReserve: hasLoadedTriangleSource() });
        return columns;
      }

      function getMethodColumnWidth(column) {
        const saved = Number(state.methodColumnWidths[column.id]);
        if (Number.isFinite(saved) && saved > 0) return saved;
        return METHOD_COL_DEFAULT_WIDTHS[column.type] || METHOD_COL_DEFAULT_WIDTHS.source;
      }

      function clampMethodColumnWidth(column, width) {
        const min = METHOD_COL_MIN_WIDTHS[column.type] || 40;
        const n = Number(width);
        if (!Number.isFinite(n)) return getMethodColumnWidth(column);
        return Math.max(min, Math.min(METHOD_COL_MAX_WIDTH, Math.round(n)));
      }

      function buildMethodColGroup(columns) {
        const colgroup = document.createElement("colgroup");
        columns.forEach((column) => {
          const col = document.createElement("col");
          col.dataset.colId = column.id;
          col.className = `rsCol rs${column.type[0].toUpperCase()}${column.type.slice(1)}Col`;
          col.style.width = `${getMethodColumnWidth(column)}px`;
          colgroup.appendChild(col);
        });
        return colgroup;
      }

      function getMethodTableTotalWidth(columns) {
        const sourceColumns = Array.isArray(columns) ? columns : buildMethodColumns(getDetails());
        return sourceColumns.reduce((sum, column) => sum + getMethodColumnWidth(column), 0);
      }

      function syncMethodTableTotalWidth(columns) {
        if (!els.methodGrid) return;
        const width = Math.max(1, Math.round(getMethodTableTotalWidth(columns)));
        els.methodGrid.style.width = `${width}px`;
        els.methodGrid.style.minWidth = `${width}px`;
      }

      function applyMethodColumnWidth(column, width) {
        const next = clampMethodColumnWidth(column, width);
        state.methodColumnWidths[column.id] = next;
        const col = Array.from(els.methodGrid?.querySelectorAll?.("col[data-col-id]") || [])
          .find((item) => item.dataset.colId === column.id);
        if (col) col.style.width = `${next}px`;
        const resultCol = Array.from(els.resultsGrid?.querySelectorAll?.("col[data-col-id]") || [])
          .find((item) => item.dataset.colId === column.id);
        if (resultCol) resultCol.style.width = `${next}px`;
        syncMethodTableTotalWidth();
        if (els.resultsGrid) {
          const resultsWidth = Math.max(1, Math.round(getMethodTableTotalWidth(buildResultsColumns(getDetails()))));
          els.resultsGrid.style.width = `${resultsWidth}px`;
          els.resultsGrid.style.minWidth = `${resultsWidth}px`;
        }
      }

      function startMethodColumnResize(event, column) {
        event.preventDefault();
        event.stopPropagation();
        const startX = event.clientX;
        const header = event.currentTarget?.closest?.("th");
        const startWidth = Math.round(header?.getBoundingClientRect?.().width || getMethodColumnWidth(column));
        document.body.classList.add("rsResizingColumns");
        const onMove = (moveEvent) => {
          applyMethodColumnWidth(column, startWidth + (moveEvent.clientX - startX));
        };
        const onUp = () => {
          document.body.classList.remove("rsResizingColumns");
          document.removeEventListener("mousemove", onMove);
          document.removeEventListener("mouseup", onUp);
        };
        document.addEventListener("mousemove", onMove);
        document.addEventListener("mouseup", onUp);
      }

      function syncToggleWeightsDisplayControl(details = getDetails()) {
        if (!els.weightDisplayButton) return;
        const value = state.showEffectiveWeights ? "effective" : "actual";
        els.weightDisplayButton.disabled = !details.showWeights;
        els.weightDisplayButton.title = state.showEffectiveWeights
          ? "Show read-only effective row weight percentages"
          : "Show editable numeric weights";
        syncDropdownValue(els.weightDisplayMenu, els.weightDisplayLabel, value, "Index");
        if (!details.showWeights) closeDropdown(els.weightDisplayDropdown, els.weightDisplayButton);
      }

      function focusMethodGrid() {
        if (!els.methodGrid) return;
        try {
          els.methodGrid.focus({ preventScroll: true });
        } catch {
          els.methodGrid.focus?.();
        }
      }

      function wireMethodCell(td, column, colIndex, rowIndex, copyValue = "", options = {}) {
        td.classList.add("rsMethodCell");
        td.dataset.colIndex = String(colIndex);
        td.dataset.rowIndex = String(rowIndex);
        td.dataset.cellType = column.type;
        td.dataset.copyValue = String(copyValue ?? "");
        td.setAttribute("aria-selected", "false");
        td.classList.toggle("rsHighlightedCell", isMethodCellHighlighted(colIndex, rowIndex));
        td.classList.toggle("rsHighlightAnchorCell", isMethodHighlightAnchor(colIndex, rowIndex));
        td.classList.toggle("rsHighlightedRowLabel", column.type === "origin" && isMethodRowHighlightedByRange(rowIndex));
        if (options.rowToggleColumnCount) {
          td.addEventListener("click", (event) => {
            event.preventDefault();
            event.stopPropagation();
            closeCellContextMenu();
            methodSpreadsheetTable.selectRow(rowIndex, { extend: event.shiftKey });
            focusMethodGrid();
          });
        } else {
          td.addEventListener("mousedown", (event) => {
            if (event.target?.closest?.("button")) return;
            if (event.target?.closest?.("input") && !options.allowInputSelection) return;
            startMethodCellHighlight(event, colIndex, rowIndex, {
              preserveDefault: options.preserveInputDefault && !!event.target?.closest?.("input"),
            });
          });
          td.addEventListener("mouseenter", () => extendMethodCellHighlight(colIndex, rowIndex));
        }
        td.addEventListener("contextmenu", (event) => openCellContextMenu(event, colIndex, rowIndex));
        return td;
      }

      function wireResultsCell(td, column, colIndex, rowIndex, copyValue = "", options = {}) {
        td.classList.add("rsResultsCell");
        td.dataset.colIndex = String(colIndex);
        td.dataset.rowIndex = String(rowIndex);
        td.dataset.cellType = column.type;
        td.dataset.copyValue = String(copyValue ?? "");
        td.setAttribute("aria-selected", "false");
        td.classList.toggle("rsHighlightedCell", isResultsCellHighlighted(colIndex, rowIndex));
        td.classList.toggle("rsHighlightAnchorCell", isResultsHighlightAnchor(colIndex, rowIndex));
        td.classList.toggle("rsHighlightedRowLabel", column.type === "origin" && isResultsRowHighlightedByRange(rowIndex));
        if (options.rowToggleColumnCount) {
          td.addEventListener("click", (event) => {
            event.preventDefault();
            event.stopPropagation();
            closeCellContextMenu();
            closeSourceContextMenu();
            resultsSpreadsheetTable.selectRow(rowIndex, { extend: event.shiftKey });
            focusResultsGrid();
          });
        } else {
          td.addEventListener("mousedown", (event) => {
            if (event.target?.closest?.("button")) return;
            startResultsCellHighlight(event, colIndex, rowIndex);
          });
          td.addEventListener("mouseenter", () => extendResultsCellHighlight(colIndex, rowIndex));
        }
        td.addEventListener("contextmenu", (event) => openResultsCellContextMenu(event, colIndex, rowIndex));
        return td;
      }

      function renderMethodGrid() {
        const grid = els.methodGrid;
        if (!grid) return;
        grid.tabIndex = 0;
        syncOriginLengthOptions();
        syncRatioBasisSelector();
        const details = getDetails();
        const count = getRowCount();
        const hasBasis = !!details.ratioBasis;
        const columns = buildMethodColumns(details);
        normalizeMethodHighlight(columns, count + 1);
        syncToggleWeightsDisplayControl(details);
        syncMethodTableTotalWidth(columns);
        const colgroup = buildMethodColGroup(columns);
        const thead = document.createElement("thead");
        const hrow = document.createElement("tr");
        hrow.className = "rsColumnHeaderRow";
        columns.forEach((column, colIndex) => {
          const th = headerCell(column.label, column);
          th.className = column.className || "";
          if (column.type !== "spacer") {
            th.dataset.colIndex = String(colIndex);
            th.classList.toggle("rsHighlightedColumnLabel", isMethodColumnHighlighted(colIndex));
            th.addEventListener("click", (event) => {
              if (event.target?.closest?.(".rsColumnResizeHandle")) return;
              event.preventDefault();
              event.stopPropagation();
              closeCellContextMenu();
              closeSourceContextMenu();
              methodSpreadsheetTable.selectColumn(colIndex, { extend: event.shiftKey });
              focusMethodGrid();
            });
          }
          if (column.type === "source") {
            th.addEventListener("contextmenu", (event) => openSourceContextMenu(event, column.sourceIndex));
            th.addEventListener("dblclick", (event) => {
              if (event.target?.closest?.(".rsColumnResizeHandle")) return;
              event.preventDefault();
              event.stopPropagation();
              closeCellContextMenu();
              closeSourceContextMenu();
              void viewOrEditSourceDataset(column.sourceIndex)
                .catch((err) => postStatus(`Open source dataset failed: ${err?.message || err}`, "error"));
            });
          }
          hrow.appendChild(th);
        });
        thead.appendChild(hrow);

        const tbody = document.createElement("tbody");
        const totals = {
          source: new Array(state.sources.length).fill(0),
          ultimate: 0,
          reserve: 0,
          basis: 0,
        };
        for (let r = 0; r < count; r += 1) {
          const tr = document.createElement("tr");
          let rowUltimateValue = null;
          columns.forEach((column, colIndex) => {
            if (column.type === "origin") {
              const label = originLabel(r);
              tr.appendChild(wireMethodCell(
                bodyCell(label, "rsOriginCell"),
                column,
                colIndex,
                r,
                label,
                { rowToggleColumnCount: columns.length }
              ));
            } else if (column.type === "source") {
              const source = state.sources[column.sourceIndex];
              const value = numberOrNull(source?.values?.[r]);
              if (value !== null) totals.source[column.sourceIndex] += value;
              const td = bodyCell(value === null ? "0" : fmtNumber(value), "rsSourceCell");
              td.dataset.sourceIndex = String(column.sourceIndex);
              td.classList.toggle("rsSourceEmptyZero", value === null);
              td.classList.toggle("rsSelectedSourceCell", isSourceCellSelected(column.sourceIndex, r));
              td.addEventListener("dblclick", (event) => {
                event.preventDefault();
                event.stopPropagation();
                if (!isSourceCellSelectable(column.sourceIndex, r)) return;
                const nextWeight = isSourceCellSelected(column.sourceIndex, r) ? 0 : 1;
                setWeightValue(column.sourceIndex, r, nextWeight);
                markDirty();
                renderMethodGrid();
              });
              tr.appendChild(wireMethodCell(td, column, colIndex, r, value === null ? "" : String(value)));
            } else if (column.type === "weight") {
              const source = state.sources[column.sourceIndex];
              const td = document.createElement("td");
              td.className = "rsWeightCell";
              let copyValue = "";
              if (state.showEffectiveWeights) {
                const weightValue = effectiveWeightAt(column.sourceIndex, r);
                const pct = document.createElement("span");
                pct.className = "rsWeightPercent";
                pct.textContent = fmtEffectiveWeight(weightValue, details);
                pct.title = "Read-only effective row weight";
                copyValue = Number.isFinite(weightValue) ? String(weightValue) : "";
                applyWeightValueClass(td, weightValue);
                td.appendChild(pct);
              } else {
                const weightValue = Math.max(0, numberOrNull(source?.weights?.[r]) ?? 0);
                applyWeightValueClass(td, weightValue);
                td.addEventListener("dblclick", (event) => {
                  event.preventDefault();
                  event.stopPropagation();
                  setWeightValue(column.sourceIndex, r, weightValue === 0 ? 1 : 0);
                  markDirty();
                  renderMethodGrid();
                });
                const weightDisplay = document.createElement("span");
                weightDisplay.className = "rsWeightValue";
                weightDisplay.textContent = fmtWeightValue(weightValue);
                copyValue = String(weightValue);
                td.appendChild(weightDisplay);
              }
              tr.appendChild(wireMethodCell(td, column, colIndex, r, copyValue));
            } else if (column.type === "ultimate") {
              rowUltimateValue = selectedUltimateAt(r);
              if (rowUltimateValue !== null) totals.ultimate += rowUltimateValue;
              const ucell = bodyCell(fmtNumber(rowUltimateValue));
              ucell.className = "rsUltimateCell";
              ucell.classList.toggle("rsUltimateCustomValue", isUltimateOverridden(r));
              tr.appendChild(wireMethodCell(ucell, column, colIndex, r, rowUltimateValue === null ? "" : String(rowUltimateValue)));
            } else if (column.type === "reserve") {
              if (rowUltimateValue === null) rowUltimateValue = selectedUltimateAt(r);
              const reserveValue = reserveAt(r, rowUltimateValue);
              if (reserveValue !== null) totals.reserve += reserveValue;
              const reserveCell = bodyCell(fmtNumber(reserveValue));
              reserveCell.className = "rsReserveCell";
              tr.appendChild(wireMethodCell(reserveCell, column, colIndex, r, reserveValue === null ? "" : String(reserveValue)));
            } else if (column.type === "ratio") {
              const basis = numberOrNull(state.ratioBasisValues[r]);
              if (basis !== null) totals.basis += basis;
              const ratioValue = basis && rowUltimateValue !== null ? rowUltimateValue / basis : null;
              const rcell = bodyCell(fmtRatio(ratioValue));
              rcell.className = "rsRatioCell";
              tr.appendChild(wireMethodCell(rcell, column, colIndex, r, ratioValue === null ? "" : String(ratioValue)));
            } else if (column.type === "spacer") {
              tr.appendChild(bodyCell("", "rsSectionSpacerCell"));
            }
          });
          tbody.appendChild(tr);
        }
        const totalRow = document.createElement("tr");
        totalRow.className = "rsTotalRow";
        const totalRowIndex = count;
        columns.forEach((column, colIndex) => {
          if (column.type === "origin") {
            totalRow.appendChild(wireMethodCell(
              bodyCell("Total", "rsOriginCell"),
              column,
              colIndex,
              totalRowIndex,
              "Total",
              { rowToggleColumnCount: columns.length }
            ));
          } else if (column.type === "source") {
            const totalValue = totals.source[column.sourceIndex];
            totalRow.appendChild(wireMethodCell(
              bodyCell(fmtNumber(totalValue), "rsSourceCell"),
              column,
              colIndex,
              totalRowIndex,
              String(totalValue)
            ));
          } else if (column.type === "weight") {
            totalRow.appendChild(wireMethodCell(
              bodyCell("", "rsWeightCell"),
              column,
              colIndex,
              totalRowIndex,
              ""
            ));
          } else if (column.type === "ultimate") {
            const totalUltimate = bodyCell(fmtNumber(totals.ultimate));
            totalUltimate.className = "rsUltimateCell";
            totalRow.appendChild(wireMethodCell(totalUltimate, column, colIndex, totalRowIndex, String(totals.ultimate)));
          } else if (column.type === "reserve") {
            const totalReserve = bodyCell(fmtNumber(totals.reserve));
            totalReserve.className = "rsReserveCell";
            totalRow.appendChild(wireMethodCell(totalReserve, column, colIndex, totalRowIndex, String(totals.reserve)));
          } else if (column.type === "ratio") {
            const ratio = totals.basis > 0 ? totals.ultimate / totals.basis : null;
            const ratioCell = bodyCell(fmtRatio(ratio));
            ratioCell.className = "rsRatioCell";
            totalRow.appendChild(wireMethodCell(ratioCell, column, colIndex, totalRowIndex, ratio === null ? "" : String(ratio)));
          } else if (column.type === "spacer") {
            totalRow.appendChild(bodyCell("", "rsSectionSpacerCell"));
          }
        });
        tbody.appendChild(totalRow);
        grid.replaceChildren(colgroup, thead, tbody);
        applyMethodHighlightDom();
        renderResultsGrid();
        ctx.renderResultSelectionChart?.();
        ctx.rsHistory?.noteRender();
      }

      function renderResultsGrid() {
        const grid = els.resultsGrid;
        if (!grid) return;
        grid.tabIndex = 0;
        const details = getDetails();
        const count = getRowCount();
        const columns = buildResultsColumns(details);
        normalizeResultsHighlight(columns, count + 1);
        const width = Math.max(1, Math.round(getMethodTableTotalWidth(columns)));
        grid.style.width = `${width}px`;
        grid.style.minWidth = `${width}px`;
        const colgroup = buildMethodColGroup(columns);
        const thead = document.createElement("thead");
        const hrow = document.createElement("tr");
        hrow.className = "rsColumnHeaderRow";
        columns.forEach((column, colIndex) => {
          const th = headerCell(column.label, column);
          th.className = column.className || "";
          if (column.type !== "spacer") {
            th.dataset.colIndex = String(colIndex);
            th.classList.toggle("rsHighlightedColumnLabel", isResultsColumnHighlighted(colIndex));
            th.addEventListener("click", (event) => {
              if (event.target?.closest?.(".rsColumnResizeHandle")) return;
              event.preventDefault();
              event.stopPropagation();
              closeCellContextMenu();
              closeSourceContextMenu();
              resultsSpreadsheetTable.selectColumn(colIndex, { extend: event.shiftKey });
              focusResultsGrid();
            });
          }
          hrow.appendChild(th);
        });
        thead.appendChild(hrow);

        const tbody = document.createElement("tbody");
        const totals = {
          source: new Array(state.sources.length).fill(0),
          ultimate: 0,
          reserve: 0,
          basis: 0,
        };
        for (let r = 0; r < count; r += 1) {
          const tr = document.createElement("tr");
          const ultimateValue = selectedUltimateAt(r);
          const reserveValue = reserveAt(r, ultimateValue);
          const basis = numberOrNull(state.ratioBasisValues[r]);
          if (ultimateValue !== null) totals.ultimate += ultimateValue;
          if (reserveValue !== null) totals.reserve += reserveValue;
          if (basis !== null) totals.basis += basis;
          columns.forEach((column, colIndex) => {
            if (column.type === "origin") {
              const label = originLabel(r);
              tr.appendChild(wireResultsCell(
                bodyCell(label, "rsOriginCell"),
                column,
                colIndex,
                r,
                label,
                { rowToggleColumnCount: columns.length }
              ));
            } else if (column.type === "source") {
              const source = state.sources[column.sourceIndex];
              const value = numberOrNull(source?.values?.[r]);
              if (value !== null) totals.source[column.sourceIndex] += value;
              const cell = bodyCell(value === null ? "0" : fmtNumber(value), "rsSourceCell");
              cell.dataset.sourceIndex = String(column.sourceIndex);
              cell.classList.toggle("rsSourceEmptyZero", value === null);
              tr.appendChild(wireResultsCell(cell, column, colIndex, r, value === null ? "" : String(value)));
            } else if (column.type === "ultimate") {
              const cell = bodyCell(fmtNumber(ultimateValue));
              cell.className = "rsUltimateCell";
              cell.classList.toggle("rsUltimateCustomValue", isUltimateOverridden(r));
              tr.appendChild(wireResultsCell(cell, column, colIndex, r, ultimateValue === null ? "" : String(ultimateValue)));
            } else if (column.type === "reserve") {
              const cell = bodyCell(fmtNumber(reserveValue));
              cell.className = "rsReserveCell";
              tr.appendChild(wireResultsCell(cell, column, colIndex, r, reserveValue === null ? "" : String(reserveValue)));
            } else if (column.type === "ratio") {
              const ratioValue = basis && ultimateValue !== null ? ultimateValue / basis : null;
              const cell = bodyCell(fmtRatio(ratioValue));
              cell.className = "rsRatioCell";
              tr.appendChild(wireResultsCell(cell, column, colIndex, r, ratioValue === null ? "" : String(ratioValue)));
            } else if (column.type === "spacer") {
              tr.appendChild(bodyCell("", "rsSectionSpacerCell"));
            }
          });
          tbody.appendChild(tr);
        }

        const totalRow = document.createElement("tr");
        totalRow.className = "rsTotalRow";
        const totalRowIndex = count;
        columns.forEach((column, colIndex) => {
          if (column.type === "origin") {
            totalRow.appendChild(wireResultsCell(
              bodyCell("Total", "rsOriginCell"),
              column,
              colIndex,
              totalRowIndex,
              "Total",
              { rowToggleColumnCount: columns.length }
            ));
          } else if (column.type === "source") {
            const value = totals.source[column.sourceIndex];
            totalRow.appendChild(wireResultsCell(
              bodyCell(fmtNumber(value), "rsSourceCell"),
              column,
              colIndex,
              totalRowIndex,
              String(value)
            ));
          } else if (column.type === "ultimate") {
            const cell = bodyCell(fmtNumber(totals.ultimate));
            cell.className = "rsUltimateCell";
            totalRow.appendChild(wireResultsCell(cell, column, colIndex, totalRowIndex, String(totals.ultimate)));
          } else if (column.type === "reserve") {
            const cell = bodyCell(fmtNumber(totals.reserve));
            cell.className = "rsReserveCell";
            totalRow.appendChild(wireResultsCell(cell, column, colIndex, totalRowIndex, String(totals.reserve)));
          } else if (column.type === "ratio") {
            const ratio = totals.basis > 0 ? totals.ultimate / totals.basis : null;
            const cell = bodyCell(fmtRatio(ratio));
            cell.className = "rsRatioCell";
            totalRow.appendChild(wireResultsCell(cell, column, colIndex, totalRowIndex, ratio === null ? "" : String(ratio)));
          } else if (column.type === "spacer") {
            totalRow.appendChild(bodyCell("", "rsSectionSpacerCell"));
          }
        });
        tbody.appendChild(totalRow);
        grid.replaceChildren(colgroup, thead, tbody);
        applyResultsHighlightDom();
      }

      function headerCell(label, column = null) {
        const th = document.createElement("th");
        const textSpan = document.createElement("span");
        textSpan.className = "rsHeaderText";
        textSpan.textContent = String(label || "");
        th.appendChild(textSpan);
        if (column && column.type !== "spacer") {
          th.dataset.colId = column.id;
          const handle = document.createElement("span");
          handle.className = "rsColumnResizeHandle";
          handle.title = "Drag to resize column";
          handle.addEventListener("mousedown", (event) => startMethodColumnResize(event, column));
          th.appendChild(handle);
        }
        return th;
      }

      function bodyCell(label, className = "") {
        const td = document.createElement("td");
        td.textContent = String(label ?? "");
        if (className) td.className = className;
        return td;
      }

      function closeCellContextMenu() {
        if (!els.cellContextMenu) return;
        els.cellContextMenu.classList.remove("open");
        els.cellContextMenu.setAttribute("aria-hidden", "true");
        delete els.cellContextMenu.dataset.table;
      }

      function closeSourceContextMenu() {
        if (!els.sourceContextMenu) return;
        els.sourceContextMenu.classList.remove("open");
        els.sourceContextMenu.setAttribute("aria-hidden", "true");
        delete els.sourceContextMenu.dataset.sourceIndex;
        delete els.sourceContextMenu.dataset.anchorLeft;
        delete els.sourceContextMenu.dataset.anchorTop;
      }

      function positionContextMenu(menu, x, y) {
        if (!menu) return;
        const pad = 8;
        menu.style.maxWidth = `${Math.max(120, window.innerWidth - (pad * 2))}px`;
        const rect = menu.getBoundingClientRect();
        const left = Math.max(pad, Math.min(x, window.innerWidth - rect.width - pad));
        const top = Math.max(pad, Math.min(y, window.innerHeight - rect.height - pad));
        menu.style.left = `${Math.round(left)}px`;
        menu.style.top = `${Math.round(top)}px`;
      }

      function openCellContextMenu(event, colIndex, rowIndex) {
        event.preventDefault();
        event.stopPropagation();
        closeSourceContextMenu();
        methodSpreadsheetTable.prepareContextCell({ r: rowIndex, c: colIndex });
        const menu = els.cellContextMenu;
        if (!menu) return;
        menu.dataset.table = "method";
        const pasteButton = menu.querySelector('[data-rs-cell-action="paste-values"]');
        if (pasteButton) pasteButton.hidden = !(highlightedHasWeightTargets() || highlightedHasUltimateCells());
        setUltimateContextMenuVisibility();
        menu.classList.add("open");
        menu.setAttribute("aria-hidden", "false");
        positionContextMenu(menu, event.clientX, event.clientY);
      }

      function openResultsCellContextMenu(event, colIndex, rowIndex) {
        event.preventDefault();
        event.stopPropagation();
        closeSourceContextMenu();
        resultsSpreadsheetTable.prepareContextCell({ r: rowIndex, c: colIndex });
        const menu = els.cellContextMenu;
        if (!menu) return;
        menu.dataset.table = "results";
        const pasteButton = menu.querySelector('[data-rs-cell-action="paste-values"]');
        if (pasteButton) pasteButton.hidden = true;
        menu.querySelectorAll("[data-rs-ultimate-action]").forEach((button) => {
          button.hidden = true;
        });
        menu.classList.add("open");
        menu.setAttribute("aria-hidden", "false");
        positionContextMenu(menu, event.clientX, event.clientY);
      }

      function openSourceContextMenu(event, sourceIndex) {
        event.preventDefault();
        event.stopPropagation();
        closeCellContextMenu();
        const menu = els.sourceContextMenu;
        if (!menu || !state.sources[sourceIndex]) return;
        menu.dataset.sourceIndex = String(sourceIndex);
        menu.dataset.anchorLeft = String(event.clientX);
        menu.dataset.anchorTop = String(event.clientY);
        menu.classList.add("open");
        menu.setAttribute("aria-hidden", "false");
        positionContextMenu(menu, event.clientX, event.clientY);
      }

      function sourceContextIndex() {
        const n = Number.parseInt(els.sourceContextMenu?.dataset?.sourceIndex || "", 10);
        return Number.isInteger(n) && n >= 0 && n < state.sources.length ? n : -1;
      }

      function sourceRecordForIndex(sourceIndex) {
        const source = state.sources[sourceIndex];
        if (!source) return null;
        return cachedRows.find((row) => norm(row.name) === norm(source.name)) || null;
      }

      async function viewOrEditSourceDataset(sourceIndex) {
        const source = state.sources[sourceIndex];
        if (!source?.name) return;
        let record = sourceRecordForIndex(sourceIndex);
        if (!record) {
          await ensureDatasetCatalogLoaded().catch(() => null);
          record = sourceRecordForIndex(sourceIndex);
        }
        const sourceMethodType = text(source.methodType || record?.methodType);
        const requestId = `rs_open_source_${Date.now()}_${Math.random().toString(36).slice(2)}`;
        const onMessage = (event) => {
          const msg = event.data || {};
          if (msg.type !== "arcrho:automation-command-result" || msg.requestId !== requestId) return;
          window.removeEventListener("message", onMessage);
          if (msg.ok === false) postStatus(`Open source dataset failed: ${msg.error || "Unknown error."}`, "error");
        };
        window.addEventListener("message", onMessage);
        window.setTimeout(() => window.removeEventListener("message", onMessage), 10000);
        try {
          window.parent?.postMessage({
            type: "arcrho:automation-open-dataset",
            requestId,
            args: {
              datasetName: source.name,
              datasetTypeName: text(source.datasetType || record?.datasetTypeName || record?.datasetType || source.name),
              methodType: sourceMethodType,
              // A source produced by a method opens on that method's own page;
              // one without a method falls back to the plain dataset window.
              openMethod: !!sourceMethodType,
            },
          }, "*");
        } catch (err) {
          window.removeEventListener("message", onMessage);
          postStatus(`Open source dataset failed: ${err?.message || err}`, "error");
        }
      }

      function removeSourceAt(sourceIndex) {
        if (sourceIndex < 0 || sourceIndex >= state.sources.length) return;
        state.sources.splice(sourceIndex, 1);
        markDirty();
        renderMethodGrid();
      }

      function methodCellCopyValue(colIndex, rowIndex) {
        const cell = Array.from(els.methodGrid?.querySelectorAll?.(".rsMethodCell") || [])
          .find((td) => Number(td.dataset.colIndex) === colIndex && Number(td.dataset.rowIndex) === rowIndex);
        return cell?.dataset?.copyValue ?? "";
      }

      function highlightedMethodValuesText() {
        const ranges = normalizedMethodHighlightRanges();
        if (!ranges.length) return "";
        const h = ranges.reduce((bounds, range) => ({
          startCol: Math.min(bounds.startCol, range.startCol),
          startRow: Math.min(bounds.startRow, range.startRow),
          endCol: Math.max(bounds.endCol, range.endCol),
          endRow: Math.max(bounds.endRow, range.endRow),
        }), { ...ranges[0] });
        const rows = [];
        for (let r = h.startRow; r <= h.endRow; r += 1) {
          const cells = [];
          for (let colIndex = h.startCol; colIndex <= h.endCol; colIndex += 1) {
            cells.push(isMethodCellHighlighted(colIndex, r) ? methodCellCopyValue(colIndex, r) : "");
          }
          rows.push(cells.join("\t"));
        }
        return rows.join("\r\n");
      }

      async function writeClipboardText(value) {
        const data = String(value || "");
        if (navigator.clipboard?.writeText) {
          await navigator.clipboard.writeText(data);
          return;
        }
        const area = document.createElement("textarea");
        area.value = data;
        area.setAttribute("readonly", "true");
        area.style.position = "fixed";
        area.style.left = "-9999px";
        document.body.appendChild(area);
        area.select();
        document.execCommand("copy");
        area.remove();
      }

      async function readClipboardText() {
        if (!navigator.clipboard?.readText) throw new Error("Clipboard paste is not available in this browser.");
        return navigator.clipboard.readText();
      }

      async function copyHighlightedMethodValues() {
        if (!await methodSpreadsheetTable.copy()) return;
        closeCellContextMenu();
        focusMethodGrid();
      }

      async function copyHighlightedResultsValues() {
        await resultsSpreadsheetTable.copy();
      }

      async function pasteHighlightedMethodValues() {
        const data = await readClipboardText();
        if (!data) return;
        if (!applyHighlightedPasteText(data)) return;
        markDirty();
        closeCellContextMenu();
        renderMethodGrid();
        focusMethodGrid();
        postStatus("Pasted Result Selection values.");
      }

      function normalizeUltimateOverrides(rawOverrides, count = getRowCount()) {
        const overrides = [];
        if (Array.isArray(rawOverrides)) {
          rawOverrides.forEach((value, index) => {
            if (index >= count) return;
            const n = numberOrNull(value);
            if (n !== null) overrides[index] = n;
          });
        } else if (rawOverrides && typeof rawOverrides === "object") {
          Object.entries(rawOverrides).forEach(([key, value]) => {
            const index = Number.parseInt(key, 10);
            const n = numberOrNull(value);
            if (Number.isInteger(index) && index >= 0 && index < count && n !== null) overrides[index] = n;
          });
        }
        return overrides;
      }

      function serializedUltimateOverrides() {
        const count = getRowCount();
        return Array.from({ length: count }, (_, index) => (
          isUltimateOverridden(index) ? numberOrNull(state.ultimateOverrides[index]) : null
        ));
      }

      function setUltimateContextMenuVisibility() {
        const showUltimateActions = highlightedHasUltimateCells();
        els.cellContextMenu?.querySelectorAll?.("[data-rs-ultimate-action]").forEach((button) => {
          button.hidden = !showUltimateActions;
        });
      }

      function revertHighlightedUltimateValues() {
        const columns = buildMethodColumns(getDetails());
        let changed = false;
        forEachHighlightedMethodCell((column, rowIndex) => {
          if (column?.type === "ultimate" && clearUltimateOverride(rowIndex)) changed = true;
        }, columns);
        return changed;
      }

      function revertAllUltimateValues() {
        const changed = state.ultimateOverrides.some((value, index) => isUltimateOverridden(index));
        state.ultimateOverrides = [];
        return changed;
      }

      return {
        isSourceCellSelectable,
        isSourceCellSelected,
        syncSourceCellSelectionDom,
        setWeightValue,
        isUltimateOverridden,
        calculatedSelectedUltimateAt,
        setUltimateOverride,
        clearUltimateOverride,
        isMethodDataRow,
        applyHighlightedUltimateValue,
        highlightedHasWeightTargets,
        highlightedHasUltimateCells,
        visibleWeightSourceIndices,
        applyWeightPaste,
        applyHighlightedWeightValue,
        parseClipboardGrid,
        clipboardGridValue,
        clipboardGridColumnCount,
        pasteTargetEndRow,
        pasteTargetEndCol,
        applyHighlightedWeightGrid,
        applyHighlightedUltimateGrid,
        applyHighlightedPasteText,
        methodHighlightSessionKey,
        resetWeightEditSession,
        applyHighlightedWeightKey,
        normalizedMethodHighlight,
        isTextEntryTarget,
        isMethodCellHighlighted,
        isMethodColumnHighlighted,
        isMethodRowHighlightedByRange,
        isMethodHighlightAnchor,
        normalizedResultsHighlight,
        isResultsCellHighlighted,
        isResultsColumnHighlighted,
        isResultsRowHighlightedByRange,
        isResultsHighlightAnchor,
        setMethodHighlight,
        setResultsHighlight,
        removeMethodHighlights,
        removeResultsHighlights,
        normalizeMethodHighlight,
        normalizeResultsHighlight,
        setMethodRowHighlight,
        setMethodColumnHighlight,
        setResultsRowHighlight,
        setResultsColumnHighlight,
        isNavigableMethodColumn,
        nextNavigableMethodColumnIndex,
        focusResultsGrid,
        scrollMethodHighlightAnchorIntoView,
        scrollResultsHighlightAnchorIntoView,
        moveMethodHighlight,
        moveResultsHighlight,
        handleMethodHighlightArrowKey,
        handleResultsHighlightArrowKey,
        applyMethodHighlightDom,
        applyResultsHighlightDom,
        startMethodCellHighlight,
        startResultsCellHighlight,
        extendMethodCellHighlight,
        extendResultsCellHighlight,
        selectedUltimateAt,
        firstTriangleSource,
        hasLoadedTriangleSource,
        latestDevelopedAt,
        reserveAt,
        effectiveWeightAt,
        selectedUltimateVector,
        calculatedUltimateVector,
        fmtNumber,
        fmtRatio,
        fmtEffectiveWeight,
        fmtWeightValue,
        applyWeightValueClass,
        methodColumnId,
        sourceMethodSection,
        sourceMethodSectionOrder,
        orderedSourceEntries,
        appendSourceColumns,
        appendMethodSectionSpacer,
        ratioStatisticLabel,
        appendStatisticColumns,
        buildMethodColumns,
        buildResultsColumns,
        getMethodColumnWidth,
        clampMethodColumnWidth,
        buildMethodColGroup,
        getMethodTableTotalWidth,
        syncMethodTableTotalWidth,
        applyMethodColumnWidth,
        startMethodColumnResize,
        syncToggleWeightsDisplayControl,
        focusMethodGrid,
        wireMethodCell,
        wireResultsCell,
        renderMethodGrid,
        renderResultsGrid,
        headerCell,
        bodyCell,
        closeCellContextMenu,
        closeSourceContextMenu,
        positionContextMenu,
        openCellContextMenu,
        openSourceContextMenu,
        sourceContextIndex,
        sourceRecordForIndex,
        viewOrEditSourceDataset,
        removeSourceAt,
        methodCellCopyValue,
        highlightedMethodValuesText,
        writeClipboardText,
        readClipboardText,
        copyHighlightedMethodValues,
        copyHighlightedResultsValues,
        pasteHighlightedMethodValues,
        normalizeUltimateOverrides,
        serializedUltimateOverrides,
        setUltimateContextMenuVisibility,
        revertHighlightedUltimateValues,
        revertAllUltimateValues
      };
    }
  };
})();
