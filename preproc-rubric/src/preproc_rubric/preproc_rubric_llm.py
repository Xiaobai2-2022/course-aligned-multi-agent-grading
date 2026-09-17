from core.llm import run_llm



def run_qwen3_8(
        messages: list[dict[str, str]],
        temperature: float = 0.2,
        max_tokens: int | None = None,
) -> str:
    """
    Return generated text by Qwen 3.8 27B

    :param messages: The input prompt
    :param temperature: The temperature for Qwen 3.8 27B
    :param max_tokens: The maximum number of tokens to generate
    :return: Qwen 3.8 generated text
    """

    return run_llm(
        messages=messages,
        model="preproc-rubric",
        base_url="http://localhost:8000",
        temperature=temperature,
        max_tokens=max_tokens
    )
