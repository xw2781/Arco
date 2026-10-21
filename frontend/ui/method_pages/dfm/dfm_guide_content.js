// Specific targets precede their containers so each component gets one hint.
export const DFM_GUIDE = {
  details: [
    ["#dfmMethodName, #dfmOutputVector", "Method Identity", "Name the method and choose its output type.", [
      "Name identifies this method.", "Output Type classifies its ultimate vector.", "Use the picker to choose a type.",
    ]],
    ["#dfmDependencyMap", "Data Flow", "Choose the triangle and check related datasets.", [
      "Input Triangle supplies observed data; use ... on its box to change it.", "Precedents feed this method; dependents use its output.", "Click a box in the map to open it.",
    ]],
    ["#originLenSelect, #devLenSelect, #decimalPlaces", "Periods And Precision", "Choose period lengths and factor precision.", [
      "Origin Length groups origin periods.", "Development Length sets development intervals.", "Decimal Places sets factor precision.",
    ]],
  ],
  data: [
    ["#tableWrap", "Input Triangle", "Right-click for copy, export and colors.", [
      "Check origins, development ages and observed values.", "Select cells to copy; Export data exports the table.", "Change the input or periods on Details.",
    ]],
  ],
  ratios: [
    [".ratioMainTable th[data-col]:not([data-col='all'])", "Interactive Ratio Chart", "Double-click a development-column header.", [
      "Click points to exclude/restore; averages to select.", "Drag cutoffs to change exclusions.", "Drag axis ends to rescale; double-click to reset.", "Included All Ratios resets exclusions. Ctrl+Z undoes edits.",
    ]],
    ["#dfmSummaryFormulaPanel", "Formula Bar", "Select a User Entry cell, then type =.", [
      "Use average, dataset or Excel references.", "Drag a referenced cell's colored border to change rows.", "Ordinary averages are read-only; tail cells accept factors.",
    ]],
    [".ratioMainTable th.ratioRowHeader", "Exclusion Shortcuts", "In Edit mode, click a row label to exclude/restore it.", [
      "Ctrl+E switches Select/Edit mode.", "Selected columns: Ctrl+H/L excludes highest/lowest; Ctrl+I includes all.", "Shift/Ctrl-drag selects without excluding.", "Ctrl+Z/Y undoes/redoes edits.",
    ]],
    [".ratioMainTable", "Observed Ratios", "Right-click for data, notes, patterns and colors.", [
      "Edit mode: click or drag ratios to exclude/restore.", "Show Data reveals underlying values.", "Copy/Apply Ratio Patterns transfers exclusions.", "Also: Copy value, Cell Notes, Table Appearance.",
    ]],
    [".ratioSummaryTable th.summaryDragHandle", "Average Row Menu", "Right-click a row label to manage averages.", [
      "Custom Average adds calculated or User Entry rows.", "Rename/Delete manages rows; drag labels to reorder.", "Edit mode: click a label to select its whole row.", "Plot Table Data compares factors; click points to select.",
    ]],
    [".ratioSummaryTable", "Average Formulas", "Compare candidate factors. Right-click cells for more actions.", [
      "Edit mode: click a factor to select it.", "Cell menu: Copy Value, Cell Notes, Plot Table Data, Table Appearance.", "Copy/Apply Formula Patterns transfers selected averages.", "Paste Value: User Entry cells, Edit mode only.",
    ]],
    [".ratioSelectedTable", "Selected Pattern", "Right-click for Show Percentage Developed Curve.", [
      "Review selected, cumulative and percent-developed values.", "Plot the pattern and compare another project's curve.", "Copy value is also available here.",
    ]],
  ],
  curves: [
    [".dfmCurvesControls", "Curve Settings", "Set fitting options and future periods.", [
      "Future Dev. Periods extends the pattern.", "Free Fit C fits the C parameter.", "Weighting is fixed to Unweighted.",
    ]],
    ["#dfmCurvesWrap", "Compare Estimates", "Right-click for user columns; double-click a user-value cell to edit.", [
      "Click Include to toggle fitting inputs.", "Click a value to select; headers select whole columns.", "Right-click to add, rename or remove user columns.", "Also: Copy Value and Table Appearance.",
    ]],
  ],
  results: [
    ["#dfmRatioBasisInput, #dfmRatioBasisBtn", "Ratio Basis", "Compare the ultimate with another dataset.", [
      "Choose a triangle or vector, such as earned premium.", "Ultimate Ratio = ultimate / basis.",
    ]],
    ["#dfmUltimateRatioDecimalPlacesInput", "Ratio Display", "Set Ultimate Ratio decimal places.", [
      "Formats this percentage column only.", "Factor precision is set on Details.",
    ]],
    ["#resultsWrap", "Ultimate Review", "Right-click for copy, export and colors.", [
      "Click row/column labels to select values.", "Total sums numeric columns.", "Total Ultimate Ratio = total ultimate / total basis.",
    ]],
  ],
  notes: [
    ["#dfmNotesPage", "Method Notes", "Right-click an underlined file path for actions.", [
      "Leave editing to use Open File or Copy File Path.", "Excel paths also offer Open as Read-Only.", "Tab/Shift+Tab indents/unindents while editing.", "Save keeps notes with the method.",
    ]],
  ],
  links: [
    [".arExternalLinksTable", "Review Link Status", "Right-click workbook rows for source and link actions.", [
      "Open workbook, open read-only, copy path or open location.", "Ctrl/Cmd-click toggles rows; Shift-click selects a range.", "Refresh/Break acts on selected links; deselect for all.", "Break keeps values. Save retains link changes.",
    ]],
    ["#dfmLinksMount", "Linked Inputs", "Inspect linked sources and their destinations.", [
      "Excel links come from User Entry formulas.", "An empty list means no linked inputs.",
    ]],
  ],
  audit: [
    ["#dfmAuditLogMount", "Saved History", "Review what changed and when.", [
      "Shows saved changes, not unsaved edits.", "Guide mode adds no audit entries.",
    ]],
  ],
};
