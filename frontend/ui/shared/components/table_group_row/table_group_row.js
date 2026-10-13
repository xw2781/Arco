/**
 * Table group header row
 *
 * One collapsible group header for every grouped table: the Project Instance
 * dataset table and the Project Settings type tables. The whole row is one
 * button that toggles the group; the caret turns to show the state, and a
 * right-click asks the host for its Collapse all / Expand all menu.
 * table_group_row.css dresses it.
 */

/**
 * @param {object} options
 * @param {string} options.text - the header text, e.g. "Category: Losses".
 * @param {number} options.colSpan - columns the header spans.
 * @param {boolean} options.collapsed - whether the group's rows are hidden.
 * @param {number} [options.depth] - nesting level; deeper groups indent.
 * @param {number|null} [options.count] - records in the group; omitted when null.
 * @param {() => void} options.onToggle - called on click.
 * @param {(event: MouseEvent) => void} [options.onContextMenu] - called on right-click.
 */
export function createTableGroupRow({ text, colSpan, collapsed, depth = 0, count = null, onToggle, onContextMenu }) {
  const tr = document.createElement("tr");
  tr.className = `pi-table-group-row depth-${depth}`;
  tr.classList.toggle("collapsed", !!collapsed);
  const td = document.createElement("td");
  td.colSpan = Math.max(1, colSpan);
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "pi-table-group-button";
  btn.style.paddingLeft = `${9 + Math.max(0, depth) * 13}px`;
  btn.setAttribute("aria-expanded", collapsed ? "false" : "true");
  btn.innerHTML = `
    <svg class="pi-table-group-caret" viewBox="0 0 12 12" aria-hidden="true" focusable="false">
      <path d="M3.2 4.2h5.6L6 7.7z"></path>
    </svg>
    <span class="pi-table-group-text"></span>
  `;
  btn.querySelector(".pi-table-group-text").textContent = text;
  if (count !== null && count !== undefined) {
    const badge = document.createElement("span");
    badge.className = "pi-table-group-count";
    badge.textContent = String(count);
    badge.title = `${count} ${count === 1 ? "record" : "records"}`;
    btn.appendChild(badge);
  }
  btn.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    onToggle();
  });
  if (onContextMenu) {
    btn.addEventListener("contextmenu", (event) => {
      event.preventDefault();
      event.stopPropagation();
      onContextMenu(event);
    });
  }
  td.appendChild(btn);
  tr.appendChild(td);
  return tr;
}
