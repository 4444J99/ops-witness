import { GoogleGenerativeAI } from '@google/generative-ai';
import { execSync } from 'child_process';
import fs from 'fs';

const GEMINI_API_KEY = process.env.GEMINI_API_KEY;
if (!GEMINI_API_KEY) {
  console.error("Missing GEMINI_API_KEY environment variable");
  process.exit(1);
}

const genAI = new GoogleGenerativeAI(GEMINI_API_KEY);
// We use gemini-1.5-flash as the "Gemini Spark" equivalent for fast orchestration tasks
const model = genAI.getGenerativeModel({ model: "gemini-1.5-flash" });

const currentHour = new Date().getUTCHours();
console.log(`Starting Jules Orchestrator at UTC hour: ${currentHour}`);

async function run() {
  if (currentHour === 8) {
    console.log("Running Backlog Discovery...");
    // Simulate discovering debt by listing repos and asking Gemini to create a task
    const reposRaw = execSync("gh repo list a-organvm --limit 5 --json name -q '.[].name'").toString();
    const repos = reposRaw.split('\n').filter(Boolean);
    
    for (const repo of repos) {
      console.log(`Analyzing ${repo}...`);
      
      const prompt = `Act as an expert technical lead. We have a repository named a-organvm/${repo}. 
      Generate 1 structured GitHub issue title and description that addresses potential technical debt 
      (like updating dependencies, adding basic tests, or fixing linter warnings). 
      Format the output as strict JSON with "title" and "body" keys.`;
      
      try {
        const result = await model.generateContent(prompt);
        let text = result.response.text();
        // Extract JSON from markdown
        text = text.replace(/```json/g, '').replace(/```/g, '').trim();
        const issueData = JSON.parse(text);
        
        console.log(`Generated task for ${repo}: ${issueData.title}`);
        
        // Write to temp file for gh cli
        fs.writeFileSync('temp_issue.md', issueData.body);
        execSync(`gh issue create --repo a-organvm/${repo} --title "${issueData.title}" --body-file temp_issue.md --label "jules"`);
        console.log(`Dispatched to Jules!`);
      } catch (err) {
        console.error(`Failed to analyze ${repo}:`, err.message);
      }
    }
  } else if (currentHour === 10 || currentHour === 14) {
    console.log("Running Jules Dispatch Batch...");
    // Future expansion: Pick up from a saved backlog queue instead of generating inline
  } else if (currentHour === 19) {
    console.log("Running PR Audit...");
    const prs = execSync("gh pr list --org a-organvm --label jules --state open --json title,url").toString();
    console.log("Open Jules PRs:", prs);
  } else {
    console.log("Manual or off-schedule run. Doing a quick health check...");
  }
}

run();
