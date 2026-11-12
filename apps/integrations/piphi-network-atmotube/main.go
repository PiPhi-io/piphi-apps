package main

import (
	"log"

	"github.com/KelvinSan/piphi-network-atmotube/app"
)

func main() {
	application := app.New()
	if err := application.Router().Run(":2026"); err != nil {
		log.Fatalf("failed to run Atmotube integration: %v", err)
	}
}
