// electron-builder afterPack hook: ad-hoc sign the macOS app before the DMG is made.
// Apple Silicon refuses to run an app whose bundle no longer matches Electron's original
// signature, and the build has no Developer ID, so a local "-" signature keeps it launchable.
const { execFileSync } = require("child_process");
const path = require("path");

exports.default = async function adhocSign(context) {
  if (context.electronPlatformName !== "darwin") return;
  const appPath = path.join(context.appOutDir, `${context.packager.appInfo.productFilename}.app`);
  execFileSync("codesign", ["--force", "--deep", "--sign", "-", appPath], { stdio: "inherit" });
};
