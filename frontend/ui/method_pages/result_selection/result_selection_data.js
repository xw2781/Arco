(function () {
  const parts = window.ResultSelectionParts || (window.ResultSelectionParts = {});

  parts.installData = function installData(ctx) {
    with (ctx) {
      const SOURCE_LOAD_CONCURRENCY = 4;

      async function mapWithConcurrency(items, limit, mapper) {
        const source = Array.isArray(items) ? items : [];
        const results = new Array(source.length);
        let nextIndex = 0;
        async function worker() {
          while (nextIndex < source.length) {
            const index = nextIndex;
            nextIndex += 1;
            results[index] = await mapper(source[index], index);
          }
        }
        const workerCount = Math.min(Math.max(1, Number(limit) || 1), source.length);
        await Promise.all(Array.from({ length: workerCount }, () => worker()));
        return results;
      }

      function normalizeDatasetRows(payload) {
        const files = Array.isArray(payload?.files) ? payload.files : [];
        const byType = new Map(datasetTypeItems.map((item) => [norm(item.name), item]));
        const rows = [];
        const seen = new Set();
        for (const item of files) {
          const name = text(item?.name);
          const key = norm(name);
          if (!name || seen.has(key)) continue;
          seen.add(key);
          const datasetType = text(item?.dataset_type || name);
          const typeInfo = byType.get(norm(datasetType)) || byType.get(norm(name)) || {};
          const sourceKind = text(item?.source_kind);
          rows.push({
            name,
            datasetType,
            dataFormat: text(item?.data_format || typeInfo.dataFormat),
            originLength: validSourceOriginLength(item?.origin_length),
            category: text(item?.dataset_category || item?.category || typeInfo.category),
            methodType: text(item?.method_type),
            sourceKind,
            path: text(item?.path),
          });
        }
        return rows.sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: "base" }));
      }

      async function loadDatasetTypes() {
        if (!state.project) return;
        try {
          const payload = await fetchProjectDatasetTypeItems(state.project, { dedupeByName: true });
          datasetTypeItems = Array.isArray(payload?.items) ? payload.items : [];
        } catch (err) {
          console.warn("Result Selection dataset type load failed:", err);
          datasetTypeItems = [];
        }
      }

      async function loadCachedRows(refresh = false) {
        if (!state.project || !state.reservingClass) return [];
        const sharedPayload = !refresh && params.get("project_instance") === "1"
          ? readProjectInstanceDatasetSnapshot(state.project, state.reservingClass)
          : null;
        if (sharedPayload) {
          cachedRows = normalizeDatasetRows(sharedPayload);
          return cachedRows;
        }
        const url = new URL("/datasets/cached", window.location.origin);
        url.searchParams.set("project_name", state.project);
        url.searchParams.set("reserving_class", state.reservingClass);
        if (refresh) url.searchParams.set("refresh", "true");
        const resp = await fetch(url.toString(), { cache: "no-store" });
        const payload = await resp.json().catch(() => ({}));
        if (!resp.ok || payload?.ok === false) throw new Error(payload?.detail || `Cached dataset lookup failed (${resp.status}).`);
        cachedRows = normalizeDatasetRows(payload);
        return cachedRows;
      }

      async function ensureDatasetCatalogLoaded(options = {}) {
        const refresh = options.refresh === true;
        if (!refresh && state.datasetCatalogLoaded) return cachedRows;
        if (!refresh && state.datasetCatalogPromise) return state.datasetCatalogPromise;
        const request = Promise.all([
          loadDatasetTypes(),
          loadCachedRows(refresh),
        ]).then(() => {
          state.datasetCatalogLoaded = true;
          return cachedRows;
        });
        state.datasetCatalogPromise = request;
        try {
          return await request;
        } finally {
          if (state.datasetCatalogPromise === request) state.datasetCatalogPromise = null;
        }
      }

      function basenameFromPath(value) {
        const parts = text(value).split(/[\\/]/);
        return parts[parts.length - 1] || "";
      }

      async function loadDatasetValues(datasetName, options = {}) {
        const name = text(datasetName);
        if (!state.project || !state.reservingClass || !name) throw new Error("Missing project, reserving class, or dataset name.");
        const body = {
          project_name: state.project,
          reserving_class: state.reservingClass,
          dataset_name: name,
        };
        const csvFile = text(options.csvFile || options.csv_file);
        const originLength = validSourceOriginLength(options.originLength ?? options.origin_length);
        const developmentLength = validSourceOriginLength(options.developmentLength ?? options.development_length);
        if (csvFile) body.csv_file = csvFile;
        if (originLength && developmentLength) {
          body.origin_length = originLength;
          body.development_length = developmentLength;
          body.cumulative = options.cumulative !== false;
          body.calendar = !!options.calendar;
        }
        const resp = await fetch("/dataset/cache/load", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        const payload = await resp.json().catch(() => ({}));
        if (!resp.ok || payload?.ok === false) throw new Error(payload?.detail || payload?.error || `Dataset load failed (${resp.status}).`);
        return payload;
      }

      function engineRequestBase(source, originLength) {
        const datasetType = text(source?.datasetType || source?.dataset_type || source?.name);
        const instanceName = text(source?.name);
        return {
          Path: state.reservingClass,
          ProjectName: state.project,
          InstanceName: instanceName || datasetType,
          DatasetTypeName: datasetType || instanceName,
          Cumulative: true,
          Calendar: false,
          LocalOnly: false,
          AllowDerived: true,
          WriteSidecar: false,
        };
      }

      async function materializeEngineSourceAtLength(source, originLength) {
        const length = validSourceOriginLength(originLength);
        if (!state.project || !state.reservingClass || !text(source?.name) || !length) {
          throw new Error("Missing project, reserving class, source name, or origin length.");
        }
        const vector = isVectorSource(source);
        const base = engineRequestBase(source, length);
        const requestPayload = vector
          ? {
              ...base,
              VectorName: base.DatasetTypeName,
              PeriodLength: length,
            }
          : {
              ...base,
              TriangleName: base.DatasetTypeName,
              OriginLength: length,
              DevelopmentLength: length,
            };
        const routeRoot = vector ? "/arcrho/vec" : "/arcrho/tri";
        postStatus(`Loading ${text(source.name)} at origin length ${length}...`);
        const resp = await fetch(routeRoot, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(requestPayload),
        });
        const payload = await resp.json().catch(() => ({}));
        if (!resp.ok || payload?.ok === false) {
          throw new Error(payload?.detail || payload?.message || `Engine source generation failed (${resp.status}).`);
        }
        return payload;
      }

      async function loadMaterializedEngineDatasetPayload(source, originLength, label = "Engine source") {
        const length = validSourceOriginLength(originLength);
        const materialized = await materializeEngineSourceAtLength(source, length);
        const payload = await loadDatasetValues(source.name, {
          csvFile: basenameFromPath(materialized?.data_path),
          originLength: length,
          developmentLength: length,
          cumulative: true,
          calendar: false,
        });
        const loadedOriginLength = validSourceOriginLength(payload?.origin_length);
        if (loadedOriginLength !== length) {
          throw new Error(`${label} '${text(source.name)}' loaded at origin length ${loadedOriginLength || "unknown"} instead of ${length}.`);
        }
        return payload;
      }

      async function loadSourceDatasetPayload(source) {
        const rsOriginLength = getDetails().originLength;
        const nativeOriginLength = validSourceOriginLength(source?.originLength ?? source?.origin_length);
        if (isEngineSource(source) && rsOriginLength) {
          if (nativeOriginLength && nativeOriginLength !== rsOriginLength) {
            return loadMaterializedEngineDatasetPayload(source, rsOriginLength);
          }
          if (!nativeOriginLength) {
            try {
              const existing = await loadDatasetValues(source.name);
              if (validSourceOriginLength(existing?.origin_length) === rsOriginLength) {
                return existing;
              }
            } catch {
              // Fall through to the authoritative length-scoped engine request.
            }
            return loadMaterializedEngineDatasetPayload(source, rsOriginLength);
          }
        }
        return loadDatasetValues(source.name);
      }

      async function loadRatioBasisDatasetPayload(source) {
        const rsOriginLength = getDetails().originLength;
        if (!rsOriginLength) return loadSourceDatasetPayload(source);
        const name = text(source?.name);
        const nativeOriginLength = validSourceOriginLength(source?.originLength ?? source?.origin_length);
        if (isEngineSource(source) && nativeOriginLength !== rsOriginLength) {
          return loadSourceDatasetPayload(source);
        }

        let exactLoadError = null;
        try {
          const exactPayload = await loadDatasetValues(name, {
            originLength: rsOriginLength,
            developmentLength: rsOriginLength,
            cumulative: true,
            calendar: false,
          });
          const exactOriginLength = validSourceOriginLength(exactPayload?.origin_length);
          if (exactOriginLength === rsOriginLength) return exactPayload;
        } catch (err) {
          exactLoadError = err;
        }

        if (isEngineSource(source)) {
          try {
            return await loadMaterializedEngineDatasetPayload(source, rsOriginLength, "Ratio Basis");
          } catch (err) {
            const exactMessage = exactLoadError?.message ? ` Exact cache load failed: ${exactLoadError.message}` : "";
            throw new Error(`${err?.message || err}${exactMessage}`);
          }
        }

        const payload = await loadSourceDatasetPayload(source);
        const loadedOriginLength = validSourceOriginLength(payload?.origin_length);
        if (loadedOriginLength !== rsOriginLength && isEngineSource(payload)) {
          return loadMaterializedEngineDatasetPayload({
            ...source,
            datasetType: text(source?.datasetType || payload?.dataset_type || payload?.datasetName || name),
            dataFormat: text(source?.dataFormat || payload?.data_format),
            originLength: loadedOriginLength,
            sourceKind: text(payload?.source_kind),
          }, rsOriginLength, "Ratio Basis");
        }
        if (loadedOriginLength !== rsOriginLength) {
          const exactMessage = exactLoadError?.message ? ` ${exactLoadError.message}` : "";
          throw new Error(`Ratio Basis '${name}' loaded at origin length ${loadedOriginLength || "unknown"} instead of ${rsOriginLength}.${exactMessage}`);
        }
        return payload;
      }

      function latestDiagonal(values) {
        const rows = Array.isArray(values) ? values : [];
        return rows.map((row) => {
          const cells = Array.isArray(row) ? row : [row];
          for (let i = cells.length - 1; i >= 0; i -= 1) {
            const n = numberOrNull(cells[i]);
            if (n !== null) return n;
          }
          return null;
        });
      }

      function vectorValues(values) {
        const rows = Array.isArray(values) ? values : [];
        return rows.map((row) => {
          if (Array.isArray(row)) return numberOrNull(row[0]);
          return numberOrNull(row);
        });
      }

      async function buildSourceFromRecord(record, existing = null) {
        const source = {
          name: text(record?.name || existing?.name),
          datasetType: text(record?.datasetType || existing?.dataset_type || existing?.datasetType),
          dataFormat: text(record?.dataFormat || existing?.data_format || existing?.dataFormat),
          originLength: validSourceOriginLength(record?.originLength ?? record?.origin_length ?? existing?.origin_length ?? existing?.originLength),
          methodType: text(record?.methodType || existing?.method_type || existing?.methodType),
          category: text(record?.category || record?.dataset_category || existing?.dataset_category || existing?.category),
          sourceKind: text(record?.sourceKind || record?.source_kind || existing?.source_kind || existing?.sourceKind),
          values: Array.isArray(existing?.values) ? existing.values.map(numberOrNull) : [],
          weights: Array.isArray(existing?.weights) ? existing.weights.map((v) => Math.max(0, numberOrNull(v) ?? 0)) : [],
          unavailable: false,
        };
        if (!source.name) return null;
        source.category = source.category || datasetTypeCategoryForName(source.datasetType || source.name);
        if (!matchesOutputCategory(source)) return null;
        try {
          const nativeOriginLength = source.originLength;
          const loadedAtRsLength = isEngineSource(source) && getDetails().originLength && nativeOriginLength !== getDetails().originLength;
          const payload = await loadSourceDatasetPayload(source);
          source.datasetType = source.datasetType || text(payload?.dataset_type || source.name);
          source.dataFormat = source.dataFormat || text(payload?.data_format);
          source.category = source.category || text(payload?.dataset_category || payload?.category) || datasetTypeCategoryForName(source.datasetType || source.name);
          if (!matchesOutputCategory(source)) return null;
          source.sourceKind = source.sourceKind || text(payload?.source_kind);
          if (!loadedAtRsLength) {
            source.originLength = validSourceOriginLength(payload?.origin_length) || source.originLength;
          }
          const isTriangle = norm(source.dataFormat) === "triangle";
          source.values = isTriangle ? latestDiagonal(payload?.values) : vectorValues(payload?.values);
        } catch (err) {
          console.warn("Result Selection source load failed:", source.name, err);
          source.unavailable = true;
        }
        if (source.weights.length < source.values.length) {
          source.weights = source.weights.concat(new Array(source.values.length - source.weights.length).fill(0));
        }
        return source;
      }

      function buildSourceFromPersisted(existing) {
        const source = existing && typeof existing === "object" ? existing : {};
        const name = text(source.name);
        if (!name) return null;
        const values = Array.isArray(source.values) ? source.values.map(numberOrNull) : [];
        const weights = Array.isArray(source.weights)
          ? source.weights.map((value) => Math.max(0, numberOrNull(value) ?? 0))
          : [];
        while (weights.length < values.length) weights.push(0);
        return {
          name,
          datasetType: text(source.dataset_type || source.datasetType),
          dataFormat: text(source.data_format || source.dataFormat),
          originLength: validSourceOriginLength(source.origin_length || source.originLength),
          methodType: text(source.method_type || source.methodType),
          category: text(source.category || source.dataset_category),
          sourceKind: text(source.source_kind || source.sourceKind),
          values,
          weights,
          unavailable: false,
        };
      }

      function getRowCount() {
        if (originLabelsKey() === state.originLabelsKey && state.originLabels.length) {
          return state.originLabels.length;
        }
        return FALLBACK_ORIGIN_LABEL_COUNTS[getDetails().originLength] || getDetails().originLength;
      }

      function originLabelsKey(originLength = getDetails().originLength) {
        return `${state.project}||${validOriginLength(originLength)}`;
      }

      function setOriginLabels(labels, originLength = getDetails().originLength) {
        state.originLabels = Array.isArray(labels) ? labels.map(String) : [];
        state.originLabelsKey = originLabelsKey(originLength);
      }

      function shouldRejectOriginLabels(originLength, labels = []) {
        return !validateDatasetOriginLabels(labels, {
          originLen: validOriginLength(originLength),
          requireMatchingPeriod: true,
        }).ok;
      }

      function applyOriginLength(value) {
        const n = validOriginLength(value, 0);
        if (!n) return false;
        withProgrammatic(() => {
          els.originLengthInput.value = String(n);
        });
        syncOriginLengthDropdownOptions();
        return true;
      }

      function syncOriginLengthDropdownOptions() {
        const input = els.originLengthInput;
        const menu = els.originLengthMenu;
        if (!input || !menu) return "";
        const options = Array.from(input.options || [])
          .map((option) => text(option.value || option.textContent))
          .filter(Boolean);
        const selected = text(input.value || options[0] || DEFAULT_ORIGIN_LENGTH);
        menu.replaceChildren(...options.map((value) => makeDropdownOption(value, value, value === selected)));
        return syncDropdownValue(menu, els.originLengthLabel, selected, selected);
      }

      function allowedOriginLengthsForSources() {
        const required = state.sources.reduce((max, source) => {
          if (isEngineSource(source)) return max;
          const originLength = validSourceOriginLength(source?.originLength);
          return originLength ? Math.max(max, originLength) : max;
        }, 0);
        return VALID_ORIGIN_LENGTHS.filter((originLength) => !required || originLength >= required);
      }

      function syncOriginLengthOptions() {
        const input = els.originLengthInput;
        if (!input) return false;
        const allowed = allowedOriginLengthsForSources();
        const current = validOriginLength(input.value, DEFAULT_ORIGIN_LENGTH);
        const fallback = allowed[allowed.length - 1] || DEFAULT_ORIGIN_LENGTH;
        const next = allowed.includes(current) ? current : fallback;
        const existing = Array.from(input.options || []).map((option) => Number.parseInt(option.value, 10));
        const needsOptions = existing.length !== allowed.length || existing.some((value, index) => value !== allowed[index]);
        if (needsOptions) {
          input.replaceChildren(...allowed.map((originLength) => {
            const option = document.createElement("option");
            option.value = String(originLength);
            option.textContent = String(originLength);
            return option;
          }));
        }
        withProgrammatic(() => {
          input.value = String(next);
        });
        syncOriginLengthDropdownOptions();
        if (next === current) return false;
        state.sidecarOriginLength = null;
        state.sidecarOriginLabels = [];
        setOriginLabels([], next);
        return true;
      }

      function originLabel(rowIndex) {
        const originLength = getDetails().originLength;
        const label = Array.isArray(state.originLabels) ? state.originLabels[rowIndex] : "";
        if (text(label)) return formatDatasetOriginLabel(label, originLength);
        return "";
      }

      async function refreshOriginLabels(options = {}) {
        const originLength = getDetails().originLength;
        const key = originLabelsKey(originLength);
        state.originLabelsKey = key;
        if (!state.project) {
          setOriginLabels([], originLength);
          if (options.render !== false) renderMethodGrid();
          return;
        }
        try {
          const labels = await ensureDatasetOriginLabels(state.project, originLength, {
            forceRefresh: !!options.forceRefresh,
          });
          if (state.originLabelsKey !== key) return;
          setOriginLabels(labels, originLength);
        } catch (err) {
          if (state.originLabelsKey !== key) return;
          setOriginLabels([], originLength);
          if (options.render !== false) renderMethodGrid();
          throw err;
        }
        if (options.render !== false) renderMethodGrid();
      }

      let outputSidecarLoadSequence = 0;

      function invalidateOutputSidecarLoad() {
        outputSidecarLoadSequence += 1;
      }

      async function loadOutputSidecarSettings(options = {}) {
        const requestSequence = ++outputSidecarLoadSequence;
        const datasetName = text(els.nameInput.value);
        if (!state.project || !state.reservingClass || !datasetName) {
          auditLogView.clear();
          return false;
        }
        auditLogView.setLoading();
        try {
          const result = await fetchPersistedResultSelection(false);
          if (requestSequence !== outputSidecarLoadSequence) return false;
          return applyOutputSidecar(result.sidecar, options);
        } catch (err) {
          if (requestSequence !== outputSidecarLoadSequence) return false;
          auditLogView.setError(err?.message || "Audit log load failed.");
          throw err;
        }
      }
      function sourceNameAlreadyLoaded(name) {
        const key = norm(name);
        return !!key && state.sources.some((source) => norm(source.name) === key);
      }

      function isSourcePickerDataFormat(record) {
        const fmt = norm(record?.dataFormat || record?.data_format);
        return fmt === "vector" || fmt === "triangle";
      }

      function isAllowedLoadedDatasetRecord(record, options = {}) {
        const name = text(record?.name);
        if (!name) return false;
        if (options.excludeOutput !== false && norm(name) === norm(els.nameInput.value)) return false;
        if (options.excludeLoaded && sourceNameAlreadyLoaded(name)) return false;
        if (!isSourcePickerDataFormat(record)) return false;
        return matchesOutputCategory(record);
      }

      function cachedSourceRecordByName(name) {
        const key = norm(name);
        return cachedRows.find((row) => norm(row.name) === key) || null;
      }

      async function openAddSourcePicker(anchor = null) {
        if (!state.project) {
          postStatus("Select a project before adding a Result Selection source.", "warn");
          return;
        }
        await ensureDatasetCatalogLoaded();
        const outputCategory = getOutputCategory();
        await openDatasetNamePicker({
          projectName: state.project,
          initialName: "",
          anchorElement: anchor instanceof Element ? anchor : null,
          title: "Add Result Selection Source",
          allowedDataFormats: ["Triangle", "Vector"],
          includeCalculated: true,
          emptyMessage: outputCategory
            ? `No cached triangle or vector source datasets found for category "${outputCategory}".`
            : "No cached triangle or vector source datasets found.",
          itemFilter: (item) => {
            const record = cachedSourceRecordByName(item?.name);
            return !!record && isAllowedLoadedDatasetRecord(record, { excludeLoaded: true });
          },
          setStatus: (message) => {
            const msg = text(message);
            if (msg) postStatus(msg, "warn");
          },
          onError: (err) => {
            console.error("Failed to open Result Selection source picker:", err);
            postStatus(`Error loading source dataset names: ${String(err?.message || err)}`, "error");
          },
          onSelect: (name) => {
            const record = cachedSourceRecordByName(name);
            if (!record || !isAllowedLoadedDatasetRecord(record, { excludeLoaded: true })) {
              postStatus("Only cached datasets with the same Category can be added as Result Selection sources.", "warn");
              return;
            }
            void addSource(record);
          },
        });
      }

      function compareSourceNames(left, right) {
        return text(left?.name).localeCompare(text(right?.name), undefined, {
          numeric: true,
          sensitivity: "base",
        });
      }

      function compareSourceDisplayOrder(left, right) {
        const sectionDelta = sourceMethodSectionOrder(sourceMethodSection(left)) - sourceMethodSectionOrder(sourceMethodSection(right));
        return sectionDelta || compareSourceNames(left, right);
      }

      function insertSourceAlphabetically(source) {
        const insertAt = state.sources.findIndex((existing) => compareSourceDisplayOrder(existing, source) > 0);
        if (insertAt === -1) state.sources.push(source);
        else state.sources.splice(insertAt, 0, source);
      }

      function pruneLoadedSourcesForOutputCategory() {
        const before = state.sources.length;
        state.sources = state.sources.filter((source) => matchesOutputCategory(source));
        return before - state.sources.length;
      }

      async function addSource(record) {
        if (state.sources.some((source) => norm(source.name) === norm(record.name))) return;
        if (!isAllowedLoadedDatasetRecord(record, { excludeLoaded: true })) {
          postStatus("Only datasets with the same Category can be added as Result Selection sources.", "warn");
          return;
        }
        const source = await buildSourceFromRecord(record);
        if (!source) return;
        const count = Math.max(getRowCount(), source.values.length);
        while (source.weights.length < count) source.weights.push(0);
        insertSourceAlphabetically(source);
        markDirty();
        renderMethodGrid();
      }

      function defaultSourceRecords() {
        return cachedRows.filter((row) => (
          norm(row.methodType) === "dfm"
          && norm(row.dataFormat) === "vector"
          && isAllowedLoadedDatasetRecord(row)
        ));
      }

      async function initializeDefaultSources() {
        const records = defaultSourceRecords();
        state.sources = (await mapWithConcurrency(
          records,
          SOURCE_LOAD_CONCURRENCY,
          (record) => buildSourceFromRecord(record),
        )).filter(Boolean);
      }

      async function reloadSourcesForCurrentOriginLength(options = {}) {
        const seq = (state.sourceReloadSeq || 0) + 1;
        state.sourceReloadSeq = seq;
        const existingSources = Array.isArray(state.sources) ? state.sources : [];
        const sources = await mapWithConcurrency(existingSources, SOURCE_LOAD_CONCURRENCY, async (existing) => {
          if (state.sourceReloadSeq !== seq) return null;
          const record = cachedRows.find((row) => norm(row.name) === norm(existing.name)) || null;
          const source = await buildSourceFromRecord(record || { name: existing.name }, existing);
          return state.sourceReloadSeq === seq ? source : null;
        });
        if (state.sourceReloadSeq !== seq) return false;
        state.sources = sources.filter(Boolean);
        if (options.render !== false) renderMethodGrid();
        return true;
      }

      async function loadRatioBasisValuesByName(basis) {
        const record = cachedRows.find((row) => norm(row.name) === norm(basis)) || { name: basis };
        const source = {
          name: text(record.name),
          datasetType: text(record.datasetType || record.dataset_type || record.name),
          dataFormat: text(record.dataFormat || record.data_format),
          originLength: validSourceOriginLength(record.originLength ?? record.origin_length),
          sourceKind: text(record.sourceKind || record.source_kind),
        };
        const payload = await loadRatioBasisDatasetPayload(source);
        return norm(record.dataFormat || payload.data_format) === "triangle"
          ? latestDiagonal(payload.values)
          : vectorValues(payload.values);
      }

      async function refreshRatioBasisValues() {
        const seq = (state.ratioBasisReloadSeq || 0) + 1;
        state.ratioBasisReloadSeq = seq;
        syncRatioBasisSelector();
        const basis = getActiveRatioBasisName();
        const contextKey = [
          text(state.project),
          text(state.reservingClass),
          String(getDetails().originLength || ""),
          norm(basis),
        ].join("||");
        const refreshIsCurrent = () => (
          state.ratioBasisReloadSeq === seq
          && contextKey === [
            text(state.project),
            text(state.reservingClass),
            String(getDetails().originLength || ""),
            norm(getActiveRatioBasisName()),
          ].join("||")
        );
        const postRefreshStatus = (message, tone = "") => {
          if (!refreshIsCurrent()) return false;
          postStatus(message, tone);
          return true;
        };
        if (!basis) {
          if (refreshIsCurrent()) {
            state.ratioBasisValues = [];
            state.ratioBasisValueSets = [];
            postRefreshStatus("Ratio Basis cleared.");
            renderMethodGrid();
          }
          return refreshIsCurrent();
        }
        if (!postRefreshStatus(`Loading Ratio Basis '${basis}'...`)) return false;
        let loadFailed = false;
        try {
          const values = await loadRatioBasisValuesByName(basis);
          if (!refreshIsCurrent()) return false;
          state.ratioBasisValueSets = upsertRatioBasisValueSet(
            state.ratioBasisValueSets,
            basis,
            values,
          );
          state.ratioBasisValues = ratioBasisValuesForName(state.ratioBasisValueSets, basis);
        } catch (err) {
          if (!refreshIsCurrent()) return false;
          state.ratioBasisValues = [];
          loadFailed = true;
          postRefreshStatus(`Ratio Basis load failed: ${err?.message || err}`, "error");
        }
        if (!refreshIsCurrent()) return false;
        if (!loadFailed) postRefreshStatus(`Ratio Basis '${basis}' ready.`);
        renderMethodGrid();
        return true;
      }

      async function refreshAllRatioBasisValues() {
        const names = getRatioBasisNames();
        if (!names.length) {
          state.ratioBasisValueSets = [];
          state.ratioBasisValues = [];
          renderMethodGrid();
          return true;
        }
        await ensureDatasetCatalogLoaded();
        const sequence = (state.ratioBasisReloadSeq || 0) + 1;
        state.ratioBasisReloadSeq = sequence;
        const originLength = getDetails().originLength;
        postStatus(`Refreshing ${names.length} Ratio Basis dataset${names.length === 1 ? "" : "s"}...`);
        const loaded = await Promise.all(names.map(async (name) => ({
          name,
          values: await loadRatioBasisValuesByName(name),
        })));
        if (state.ratioBasisReloadSeq !== sequence || getDetails().originLength !== originLength) return false;
        state.ratioBasisValueSets = normalizeRatioBasisValueSets(loaded, names);
        state.ratioBasisValues = ratioBasisValuesForName(
          state.ratioBasisValueSets,
          getActiveRatioBasisName(),
        );
        renderMethodGrid();
        postStatus("Ratio Basis values refreshed.");
        return true;
      }

      function usePersistedRatioBasisValues() {
        const basis = getActiveRatioBasisName();
        const match = (Array.isArray(state.ratioBasisValueSets) ? state.ratioBasisValueSets : [])
          .find((item) => norm(item?.name) === norm(basis));
        if (!basis || !match) return false;
        state.ratioBasisValues = ratioBasisValuesForName(state.ratioBasisValueSets, basis);
        renderMethodGrid();
        return true;
      }

      async function useOrRefreshRatioBasisValues() {
        if (usePersistedRatioBasisValues()) return true;
        return refreshRatioBasisValues();
      }

      async function refreshMissingRatioBasisValues() {
        const names = getRatioBasisNames();
        const stored = new Set(
          (Array.isArray(state.ratioBasisValueSets) ? state.ratioBasisValueSets : [])
            .map((item) => norm(item?.name))
            .filter(Boolean),
        );
        const missing = names.filter((name) => !stored.has(norm(name)));
        if (!missing.length) {
          return usePersistedRatioBasisValues();
        }
        const sequence = (state.ratioBasisReloadSeq || 0) + 1;
        state.ratioBasisReloadSeq = sequence;
        const contextKey = [
          text(state.project),
          text(state.reservingClass),
          String(getDetails().originLength || ""),
          names.map(norm).join("|"),
        ].join("||");
        await ensureDatasetCatalogLoaded();
        const loaded = await Promise.all(missing.map(async (name) => ({
          name,
          values: await loadRatioBasisValuesByName(name),
        })));
        const currentContextKey = [
          text(state.project),
          text(state.reservingClass),
          String(getDetails().originLength || ""),
          getRatioBasisNames().map(norm).join("|"),
        ].join("||");
        if (state.ratioBasisReloadSeq !== sequence || currentContextKey !== contextKey) return false;
        for (const item of loaded) {
          state.ratioBasisValueSets = upsertRatioBasisValueSet(
            state.ratioBasisValueSets,
            item.name,
            item.values,
          );
        }
        state.ratioBasisValueSets = normalizeRatioBasisValueSets(state.ratioBasisValueSets, names);
        state.ratioBasisValues = ratioBasisValuesForName(
          state.ratioBasisValueSets,
          getActiveRatioBasisName(),
        );
        renderMethodGrid();
        return true;
      }

      async function restoreCleanState() {
        if (!cleanSnapshot) return;
        const snapshot = JSON.parse(cleanSnapshot);
        await applyPayload(snapshot.method || {});
        setNotesText(String(snapshot.notes ?? ""));
        markClean();
      }

      // Undo and redo land on a snapshot taken by the page history. Source and
      // Ratio Basis loads still in flight belong to the state being left, so
      // their sequence numbers move on and their results are dropped.
      async function restoreHistorySnapshot(snapshotText) {
        const snapshot = JSON.parse(snapshotText);
        state.sourceReloadSeq = Number(state.sourceReloadSeq || 0) + 1;
        state.ratioBasisReloadSeq = Number(state.ratioBasisReloadSeq || 0) + 1;
        await applyPayload(snapshot.method || {});
        setNotesText(String(snapshot.notes ?? ""));
        if (snapshotText === cleanSnapshot) {
          clearResultSelectionDependencyPreview("clean");
          postDirty(false, true);
        } else {
          postDirty(true);
          postResultSelectionDependencyPreview();
        }
      }

      async function openRatioBasisDatasetPicker() {
        const names = getRatioBasisNames();
        if (names.length >= MAX_RATIO_BASIS_COUNT) {
          postStatus(`A maximum of ${MAX_RATIO_BASIS_COUNT} Ratio Basis datasets is allowed.`, "warn");
          return;
        }
        const input = (els.ratioBasisInputs || []).find((candidate) => candidate && !text(candidate.value)) || null;
        const button = els.ratioBasisAddButton || null;
        if (!input) return;
        if (!state.project) {
          postStatus("Select a project before choosing a Ratio Basis dataset.", "warn");
          return;
        }
        await ensureDatasetCatalogLoaded();
        if (button) button.disabled = true;
        try {
          await openDatasetNamePicker({
            projectName: state.project,
            initialName: "",
            anchorElement: button,
            title: "Add Ratio Basis",
            includeCalculated: true,
            setStatus: (message) => {
              const msg = text(message);
              if (msg) postStatus(msg, "warn");
            },
            onError: (err) => {
              console.error("Failed to open Ratio Basis picker:", err);
              postStatus(`Error loading ratio-basis dataset names: ${String(err?.message || err)}`, "error");
            },
            onSelect: (name) => {
              const selected = text(name);
              if (!selected) return;
              if (matchRatioBasisName(selected, getRatioBasisNames())) {
                postStatus(`Ratio Basis is already selected: ${selected}`, "warn");
                return;
              }
              input.value = selected;
              input.dispatchEvent(new Event("change", { bubbles: true }));
            },
          });
        } finally {
          if (button) button.disabled = getRatioBasisNames().length >= MAX_RATIO_BASIS_COUNT;
        }
      }

      return {
        SOURCE_LOAD_CONCURRENCY,
        mapWithConcurrency,
        normalizeDatasetRows,
        loadDatasetTypes,
        loadCachedRows,
        ensureDatasetCatalogLoaded,
        basenameFromPath,
        loadDatasetValues,
        engineRequestBase,
        materializeEngineSourceAtLength,
        loadMaterializedEngineDatasetPayload,
        loadSourceDatasetPayload,
        loadRatioBasisDatasetPayload,
        latestDiagonal,
        vectorValues,
        buildSourceFromRecord,
        buildSourceFromPersisted,
        getRowCount,
        originLabelsKey,
        setOriginLabels,
        shouldRejectOriginLabels,
        applyOriginLength,
        syncOriginLengthDropdownOptions,
        allowedOriginLengthsForSources,
        syncOriginLengthOptions,
        originLabel,
        refreshOriginLabels,
        invalidateOutputSidecarLoad,
        loadOutputSidecarSettings,
        sourceNameAlreadyLoaded,
        isSourcePickerDataFormat,
        isAllowedLoadedDatasetRecord,
        cachedSourceRecordByName,
        openAddSourcePicker,
        compareSourceNames,
        compareSourceDisplayOrder,
        insertSourceAlphabetically,
        pruneLoadedSourcesForOutputCategory,
        addSource,
        defaultSourceRecords,
        initializeDefaultSources,
        reloadSourcesForCurrentOriginLength,
        loadRatioBasisValuesByName,
        refreshRatioBasisValues,
        refreshAllRatioBasisValues,
        usePersistedRatioBasisValues,
        useOrRefreshRatioBasisValues,
        refreshMissingRatioBasisValues,
        restoreCleanState,
        restoreHistorySnapshot,
        openRatioBasisDatasetPicker
      };
    }
  };
})();
