import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const {
  assertMinimumCodexVersion,
  assertRequiredBundledModel,
  compareSemanticVersions,
  loadRuntimeContract,
  smokeBundledCodexRuntime,
  validateBundledCodexRuntime,
} = require("../build/arcbot_runtime/validate_bundled_codex_runtime.js");

const TESTS_DIR = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND_DIR = path.resolve(TESTS_DIR, "..");
const RUNTIME_ROOT = path.join(FRONTEND_DIR, "node-portable");

const readText = (relativePath) => fs.readFileSync(
  new URL(relativePath, import.meta.url),
  "utf8",
);

test("tracked ArcBot runtime contract sets the Codex CLI and model floors", () => {
  assert.deepEqual(loadRuntimeContract(), {
    schemaVersion: 1,
    minimumCodexCliVersion: "0.146.0",
    minimumDefaultModel: "gpt-5.6-sol",
  });
});

test("Codex CLI minimum comparison follows semantic-version precedence", () => {
  assert.ok(compareSemanticVersions("0.146.1", "0.146.0") > 0);
  assert.equal(compareSemanticVersions("0.146.0+build.2", "0.146.0"), 0);
  assert.ok(compareSemanticVersions("0.146.0-rc.1", "0.146.0") < 0);
  assert.throws(
    () => assertMinimumCodexVersion("0.145.9", "0.146.0"),
    /below the required minimum 0\.146\.0/iu,
  );
});

test("bundled model catalog requires the configured model to be listed", () => {
  const model = assertRequiredBundledModel(JSON.stringify({
    models: [{ slug: "gpt-5.6-sol", visibility: "list" }],
  }), "gpt-5.6-sol");
  assert.equal(model.slug, "gpt-5.6-sol");
  assert.throws(
    () => assertRequiredBundledModel(JSON.stringify({
      models: [{ slug: "gpt-5.6-sol", visibility: "hide" }],
    }), "gpt-5.6-sol"),
    /not visible/iu,
  );
  assert.throws(
    () => assertRequiredBundledModel(JSON.stringify({ models: [] }), "gpt-5.6-sol"),
    /missing required model/iu,
  );
});

test("bundled Node, npm, and Codex runtime is rejected when stale or fully smoked", async () => {
  const runtimeContract = loadRuntimeContract();
  const installedPackage = JSON.parse(fs.readFileSync(
    path.join(RUNTIME_ROOT, "node_modules", "@openai", "codex", "package.json"),
    "utf8",
  ));
  if (compareSemanticVersions(
    installedPackage.version,
    runtimeContract.minimumCodexCliVersion,
  ) < 0) {
    assert.throws(
      () => validateBundledCodexRuntime(RUNTIME_ROOT),
      new RegExp(
        `Codex CLI ${installedPackage.version} is below the required minimum ${runtimeContract.minimumCodexCliVersion}`,
        "iu",
      ),
    );
    return;
  }

  const smokeCwd = fs.mkdtempSync(path.join(TESTS_DIR, "bundled-codex-runtime-"));
  try {
    const result = await smokeBundledCodexRuntime(RUNTIME_ROOT, {
      cwd: smokeCwd,
      timeoutMs: 8_000,
    });

    assert.equal(result.runtimeRoot, fs.realpathSync(RUNTIME_ROOT));
    assert.match(result.npmVersion, /^\d+\.\d+\.\d+/u);
    assert.match(result.codexVersion, /^codex-cli\s+\d+\.\d+\.\d+/u);
    assert.equal(result.codexCliVersion, result.codexPackageVersion);
    assert.equal(result.requiredModel.slug, runtimeContract.minimumDefaultModel);
    assert.equal(result.requiredModel.visibility, "list");
    for (const filePath of Object.values(result.files)) {
      assert.ok(fs.statSync(filePath).isFile(), filePath);
      assert.ok(fs.statSync(filePath).size > 0, filePath);
    }
    assert.doesNotMatch(result.cwd, /\.asar(?:[\\/]|$)/iu);
  } finally {
    fs.rmSync(smokeCwd, { recursive: true, force: true });
  }
});

test("runtime inventory rejects an incomplete portable Node directory", () => {
  const incompleteRoot = fs.mkdtempSync(path.join(TESTS_DIR, "incomplete-codex-runtime-"));
  try {
    assert.throws(
      () => validateBundledCodexRuntime(incompleteRoot),
      /node\.exe is missing/iu,
    );
  } finally {
    fs.rmSync(incompleteRoot, { recursive: true, force: true });
  }
});

test("ArcRho and Arcode package node-portable as an external runtime resource", () => {
  const packageJson = JSON.parse(readText("../package.json"));
  const arcodeConfig = JSON.parse(readText("../electron-builder.arcode.json"));

  for (const [name, config] of [
    ["ArcRho", packageJson.build],
    ["Arcode", arcodeConfig],
  ]) {
    assert.ok(config.files.includes("!node-portable/**"), `${name} must keep node-portable out of app.asar`);
    assert.deepEqual(
      config.extraResources.find((resource) => resource.from === "node-portable"),
      { from: "node-portable", to: "node-portable" },
      `${name} must copy the complete portable runtime beside app.asar`,
    );
  }
});

test("source ZIP validation requires the full npm and Codex payload", () => {
  const sourceZip = readText("../build/transport/create_build_source_zip.ps1");
  for (const requiredPath of [
    "frontend/build/arcbot_runtime/refresh_bundled_codex_runtime.ps1",
    "frontend/build/arcbot_runtime/validate_bundled_codex_runtime.js",
    "frontend/electron/arcbot_runtime_contract.json",
    "frontend/node-portable/node.exe",
    "frontend/node-portable/npm.cmd",
    "frontend/node-portable/node_modules/npm/bin/npm-cli.js",
    "frontend/node-portable/codex.cmd",
    "frontend/node-portable/node_modules/@openai/codex/bin/codex.js",
    "node_modules/@openai/codex-win32-x64/vendor/x86_64-pc-windows-msvc/bin/codex.exe",
  ]) {
    assert.ok(sourceZip.includes(`"${requiredPath}"`), `ZIP contract is missing ${requiredPath}`);
  }
  assert.match(sourceZip, /--runtime-root \$bundledRuntimeRoot --inventory-only/u);
});

test("bundled runtime refresh reads the tracked CLI version contract", () => {
  const refreshScript = readText("../build/arcbot_runtime/refresh_bundled_codex_runtime.ps1");
  assert.match(refreshScript, /arcbot_runtime_contract\.json/u);
  assert.match(refreshScript, /minimumCodexCliVersion/u);
  assert.match(refreshScript, /"@openai\/codex@\$codexVersion"/u);
  assert.match(refreshScript, /validate_bundled_codex_runtime\.js/u);
});

test("the one-click build smokes source and packaged runtimes before publication and cleanup", () => {
  const wrapper = readText("../build/build_app_via_local_workspace.bat");
  const sourceSmokeAt = wrapper.indexOf('call :validate_bundled_codex_runtime "%NODE_HOME%" "%APP_ROOT%"');
  const electronBuildAt = wrapper.indexOf("call :run_electron");
  const packagedRootAt = wrapper.indexOf("dist\\win-unpacked\\resources\\node-portable");
  const packagedSmokeAt = wrapper.indexOf(
    'call :validate_bundled_codex_runtime "%PACKAGED_NODE_HOME%" "%APP_ROOT%"',
  );
  const publishAt = wrapper.indexOf("Step 6: Publishing GitHub Release");
  const cleanupAt = wrapper.indexOf('rmdir /s /q "dist\\win-unpacked"');

  assert.ok(sourceSmokeAt >= 0 && sourceSmokeAt < electronBuildAt);
  assert.ok(electronBuildAt < packagedRootAt && packagedRootAt < packagedSmokeAt);
  assert.ok(packagedSmokeAt < publishAt && publishAt < cleanupAt);
  assert.match(
    wrapper,
    /call "%~1\\node\.exe" "%APP_ROOT%\\build\\arcbot_runtime\\validate_bundled_codex_runtime\.js"/u,
  );
  // The smoke test runs seconds after the source ZIP is unpacked, so the first
  // launch of the extracted native runtime must not be mistaken for a failure.
  const wrapperTimeout = /--timeout-ms (\d+)/u.exec(wrapper);
  assert.ok(wrapperTimeout);
  assert.ok(
    Number(wrapperTimeout[1]) >= 30_000,
    "the one-click build must tolerate a cold-start runtime launch",
  );
});

test("the one-click build publishes only to GitHub Releases", () => {
  const wrapper = readText("../build/build_app_via_local_workspace.bat");
  assert.ok(
    !wrapper.includes("publish_update_feed.ps1"),
    "the build must not publish the installer to the network update feed",
  );
  assert.ok(
    !wrapper.includes("RELEASE_FEED_DIR") && !wrapper.includes("UPDATE_FEED_DIR"),
    "the retired network feed directory must not survive in the build wrapper",
  );
  assert.match(wrapper, /publish_github_release\.ps1/u);
  assert.match(wrapper, /version_manager\.py --github-release-product "%PRODUCT_NAME%"/u);
});

test("a published release can be synced back into the repository", () => {
  const sync = readText("../build/release/sync_published_release.py");
  assert.match(sync, /git", "ls-remote"/u, "the tag check must not require the gh CLI");
  assert.match(sync, /version_manager\.update_version_metadata/u);
  assert.match(sync, /release_notes\.release_fragments/u);
  assert.match(sync, /read_zip_fragment_names/u);

  const versionManager = readText("../build/release/version_manager.py");
  assert.match(versionManager, /def update_version_metadata/u);
  assert.ok(
    !/^\s*sync_package_lock\(package_lock_path/mu.test(versionManager),
    "main must write version metadata through update_version_metadata, not inline",
  );

  const notes = readText("../build/release/release_notes.py");
  assert.match(notes, /def release_fragments/u);

  const wrapper = readText("../build/build_app_via_local_workspace.bat");
  assert.match(wrapper, /request_release_sync\.ps1/u);
  // The wrapper lists its main flow before its subroutines, so ordering is asserted on
  // the calls in that flow rather than on where the labelled bodies happen to sit.
  assert.ok(
    wrapper.indexOf("call :sync_source_repository") > wrapper.indexOf("call :build_local_application"),
    "the repository sync must run after the build that publishes the release",
  );
  assert.match(wrapper, /sync_published_release\.bat %APP_VERSION%/u, "a manual fallback must be printed");

  const requester = readText("../build/release/request_release_sync.ps1");
  assert.match(requester, /kind\s+= "syncRelease"/u);

  const zipContract = readText("../build/transport/create_build_source_zip.ps1");
  assert.ok(
    zipContract.includes('"frontend/build/release/request_release_sync.ps1"'),
    "the build PC needs the sync requester inside the ZIP",
  );
});

test("a local release build runs in the repository and skips the ZIP transport", () => {
  const local = readText("../build/build_app_from_local_repo.bat");
  const wrapper = readText("../build/build_app_via_local_workspace.bat");

  // The local entry point must reuse the shared build body rather than restating the
  // packaging steps, so a change to packaging cannot apply to only one of the two routes.
  assert.match(local, /build_app_via_local_workspace\.bat/u);
  assert.match(local, /set "ARCRHO_BUILD_IN_PLACE=1"/u);
  assert.match(local, /set "ARCRHO_LOCAL_BUILD_ROOT=%REPO_ROOT%"/u);
  assert.ok(
    !local.includes("create_build_source_zip"),
    "a single-PC build must not cut a source ZIP to hand the repository to itself",
  );

  // In-place mode must skip both halves of the transport: waiting for a ZIP that is never
  // published, and extracting one over the repository it is building from.
  assert.ok(
    wrapper.indexOf("if defined ARCRHO_BUILD_IN_PLACE goto workspace_ready") <
      wrapper.indexOf("call :wait_for_new_source_zip_signal"),
    "in-place mode must branch past the ZIP wait",
  );
  assert.ok(
    wrapper.indexOf(":workspace_ready") >
      wrapper.indexOf("prepare_local_build_workspace_from_zip.ps1"),
    "in-place mode must rejoin after workspace extraction",
  );

  // The wrapper runs under setlocal, so the caller can only learn the built version
  // through the handover file.
  assert.match(wrapper, /ARCRHO_BUILD_VERSION_OUT/u);
  assert.match(local, /set "ARCRHO_BUILD_VERSION_OUT=%VERSION_OUT%"/u);
});

test("an in-place build records its release without reconstructing it", () => {
  const local = readText("../build/build_app_from_local_repo.bat");
  const sync = readText("../build/release/sync_published_release.py");

  assert.match(local, /--bookkeeping-only/u);
  assert.ok(
    !local.includes("--source-zip"),
    "there is no build ZIP to read a fragment list from; the build consumed the fragments itself",
  );

  // The build already wrote the release work, so redoing it here would regenerate notes
  // from fragments the release already drained.
  assert.match(sync, /def commit_bookkeeping_only/u);
  const bookkeeping = sync.slice(
    sync.indexOf("def commit_bookkeeping_only"),
    sync.indexOf("def read_zip_fragment_names"),
  );
  assert.ok(
    !bookkeeping.includes("release_fragments") &&
      !bookkeeping.includes("update_version_metadata"),
    "bookkeeping-only must never redo the release work the build already did",
  );
  assert.match(bookkeeping, /commit_release_bookkeeping/u, "it must reuse the shared staging list");
  assert.match(bookkeeping, /update_docs_index/u);
});

test("the build share launchers are version controlled and deployed from the repository", () => {
  for (const name of [
    "build_app_listener.bat",
    "build_app_listener.ps1",
    "build_app_one_click.bat",
    "build_arcode_one_click.bat",
    "publish_pending_github_release.bat",
  ]) {
    assert.ok(
      readText(`../build/build_share/${name}`).trim().length > 0,
      `${name} must be tracked in build/build_share`,
    );
  }

  const listener = readText("../build/build_share/build_app_listener.ps1");
  assert.match(listener, /Test-DeployedListenerIsCurrent/u, "the listener must flag itself when stale");
  assert.match(listener, /syncRelease/u);
  assert.match(listener, /Write-Warning "Build request/u, "a failed request must not kill the listener");

  const deploy = readText("../build/transport/deploy_build_share.ps1");
  assert.match(deploy, /\$Verify/u);
  assert.ok(
    !/Remove-Item/u.test(deploy),
    "the deploy must never delete anything from the share, which also holds build artifacts and logs",
  );
  assert.match(deploy, /the share copy is newer/u, "a direct share edit must not be silently overwritten");
});

test("the release sync only ever stages release bookkeeping", () => {
  const sync = readText("../build/release/sync_published_release.py");
  assert.match(sync, /"add", "-u", "frontend\/changes\/unreleased"/u);
  for (const owned of ["frontend/package.json", "frontend/docs/releases"]) {
    assert.ok(sync.includes(`"${owned}"`), `${owned} must be part of the commit scope`);
  }
  for (const foreign of ["frontend/ui/shell", "frontend/app_server", "frontend/tests"]) {
    assert.ok(!sync.includes(`"${foreign}"`), `${foreign} must never be staged by the sync`);
  }
  assert.ok(!/\bgit["'\s,\]]*push\b/u.test(sync), "the sync must never push");
});

test("release tag naming and the GitHub repository have one owner", () => {
  const channel = JSON.parse(readText("../build/release/release_channel.json"));
  assert.equal(typeof channel.githubRepo, "string");
  assert.ok(channel.githubRepo.includes("/"), "githubRepo must be owner/name");
  assert.ok(channel.tagFormat.includes("{product}") && channel.tagFormat.includes("{version}"));
  assert.equal(typeof channel.updateFeedTag, "string");
  assert.ok(channel.updateFeedAsset.includes("{product}"), "each product reads its own update feed");

  const publishScript = readText("../build/release/publish_github_release.ps1");
  assert.match(publishScript, /release_channel\.json/u);
  assert.match(publishScript, /publish_update_manifest\.ps1/u, "every publish must rebuild the update feed");
  assert.ok(
    !/\$tag = "\$ProductName-v\$version"/u.test(publishScript),
    "the release tag must come from the release channel definition, not a literal",
  );
  assert.match(publishScript, /\$releaseExists = \(\$LASTEXITCODE -eq 0\)/u);
  assert.match(publishScript, /\$GITHUB_RELEASE_BODY_LIMIT = 125000/u);
  assert.ok(
    publishScript.indexOf("$notesText = \"$notesText`n`nmandatory: true\"") >
      publishScript.indexOf("$notesText.Length -gt $GITHUB_RELEASE_BODY_LIMIT"),
    "the mandatory marker must be appended after truncation so it survives a long release",
  );

  const versionManager = readText("../build/release/version_manager.py");
  assert.match(versionManager, /release_channel\.json/u);
  assert.ok(
    !versionManager.includes("collect_release_feed_versions"),
    "the retired installer feed scan must be gone",
  );
});
