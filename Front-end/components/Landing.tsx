import Link from "next/link";

const STEPS = [
  { title: "Describe the job you want", text: "Write it in your own words, and change it whenever you like." },
  { title: "We read the job sites daily", text: "New listings from Afriwork, Ethiojobs, LinkedIn and a dozen more Ethiopian, NGO and UN job sites are collected every day." },
  { title: "AI picks what suits you", text: "Only the jobs that fit are saved for you, each with a short reason." },
  { title: "Check in when it suits you", text: "Your jobs wait for you for three weeks. Apply on the original site." },
];

export function Landing() {
  return (
    <main className="landing">
      <section className="hero">
        <h1>The right jobs in Ethiopia, without the daily searching</h1>
        <p>
          Tell us what you&apos;re looking for. Every day we check new listings across Ethiopian job sites and keep the
          ones that suit you, ready when you are.
        </p>
        <div className="hero-actions">
          <Link href="/register" className="button button-primary button-large">Create your account</Link>
          <Link href="/login" className="button button-secondary button-large">Log in</Link>
        </div>
      </section>
      <ol className="steps">
        {STEPS.map((step, index) => (
          <li key={step.title}>
            <span className="step-number" aria-hidden="true">{index + 1}</span>
            <h2>{step.title}</h2>
            <p>{step.text}</p>
          </li>
        ))}
      </ol>
    </main>
  );
}
