const {defineConfig}=require('playwright/test');
const port=process.env.CARRICK_TEST_PORT||'8766';
module.exports=defineConfig({
  testDir:'./tests/browser',testMatch:'**/*.spec.cjs',workers:1,timeout:45000,expect:{timeout:10000},
  outputDir:'./output/browser-tests',reporter:[['list']],
  use:{baseURL:`http://127.0.0.1:${port}`,headless:true,permissions:['microphone'],viewport:{width:1280,height:900},
    screenshot:'only-on-failure',trace:'retain-on-failure',
    launchOptions:{...(process.env.CARRICK_CHROME_PATH?{executablePath:process.env.CARRICK_CHROME_PATH}:{}),args:['--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream']}},
  webServer:{command:`${process.env.CARRICK_TEST_PYTHON||'python3'} -m scripts.e2e_server`,url:`http://127.0.0.1:${port}/api/auth/status`,reuseExistingServer:false,timeout:15000,gracefulShutdown:{signal:'SIGINT',timeout:3000},env:{CARRICK_TEST_PORT:port}}
});
