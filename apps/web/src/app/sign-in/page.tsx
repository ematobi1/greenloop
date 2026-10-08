import SignInForm from "@/components/chat/SignInForm";

export const metadata = { title: "Sign in · GreenLoop" };

export default async function Page({ searchParams }: PageProps<"/sign-in">) {
  const expired = (await searchParams).expired === "1";
  return (
    <main className="sign-in-page">
      <SignInForm notice={expired ? "Your session has ended. Sign in again." : null} />
    </main>
  );
}
