import { Config } from "@remotion/cli/config";

Config.setVideoImageFormat("jpeg");
Config.setPixelFormat("yuv420p");
Config.setCodec("h264");
Config.setOverwriteOutput(true);

if (process.env.REMOTION_CHROMIUM_EXECUTABLE) {
  Config.setBrowserExecutable(process.env.REMOTION_CHROMIUM_EXECUTABLE);
}
