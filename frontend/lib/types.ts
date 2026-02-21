export type Message = {
  role: "user" | "assistant";
  content: string;
  status?: "thinking" | "typing" | "done";
};