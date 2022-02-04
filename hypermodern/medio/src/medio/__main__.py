"""Command-line interface."""
import click


@click.command()
@click.version_option()
def main() -> None:
    """Medio."""


if __name__ == "__main__":
    main(prog_name="medio")  # pragma: no cover
